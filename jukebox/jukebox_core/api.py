# -*- coding: UTF-8 -*-
from django.core.paginator import Paginator, InvalidPage
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, Min, Q
from django.contrib.sessions.models import Session
from django.utils import formats
import os, re, time
from datetime import datetime
from signal import SIGABRT
from django.contrib.auth.models import User
from models import Song, Artist, Album, Genre, Queue, Favourite, History, Player
from recommends.providers import recommendation_registry


class api_base:
    count = 30
    user_id = None
    search_term = None
    search_title = None
    search_artist_name = None
    search_album_title = None
    filter_year = None
    filter_genre = None
    filter_album_id = None
    filter_artist_id = None
    order_by_field = None
    order_by_direction = None
    order_by_fields = []
    order_by_directions = ["asc", "desc"]
    order_by_default = None

    def set_count(self, count):
        if count > 100:
            self.count = 100
        elif count > 0:
            self.count = count

    def set_user_id(self, user_id):
        self.user_id = user_id

    def set_search_term(self, term):
        options = self.parseSearchString(
            (
                "title",
                "artist",
                "album",
                "genre",
                "year",
            ),
            term
        )
        for key, value in options.items():
            if key == "title":
                self.set_search_title(value)
            elif key == "artist":
                self.set_search_artist_name(value)
            elif key == "album":
                self.set_search_album_title(value)
            elif key == "genre":
                try:
                    genre = Genre.objects.all().filter(Name__iexact=value)[0:1].get()
                    self.set_filter_genre(genre.id)
                except ObjectDoesNotExist:
                    pass
            elif key == "year":
                self.set_filter_year(value)

        self.search_term = options["term"]

    def parseSearchString(self, keywords, term):
        values = {}
        for i in range(len(keywords)):
            do_continue = False
            keyword = keywords[i]
            value = None
            pos = term.find(keyword + ":")
            if pos != -1:
                value_start = pos + len(keyword) + 1
                # no brackets, search for next whitespace
                if term[value_start:value_start + 1] != "(":
                    value_end = term.find(" ", value_start)
                    if value_end == -1:
                        value_end = len(term)
                        do_continue = True
                    value = term[value_start:value_end]
                # search for next closing bracket but count opened ones
                else:
                    i = value_start + 1
                    bracket_count = 1
                    while i < len(term):
                        char = term[i:i+1]
                        if char == "(":
                            bracket_count+= 1
                        elif char == ")":
                            bracket_count-= 1
                            if not bracket_count:
                                value = term[value_start:i+1]
                                continue
                        i+= 1

                    if not value:
                        value = term[value_start:len(term)]
                        do_continue = True

            if value is not None:
                values[keyword] = value
            if do_continue:
                continue

        for key, value in values.items():
            term = term.replace(key + ":" + value, "").strip()
            if value.startswith("("):
                values[key] = value[1:len(value)-1]

        values["term"] = re.sub("\s+", " ", term)
        return values

    def set_search_title(self, term):
        self.search_title = term

    def set_search_artist_name(self, term):
        self.search_artist_name = term

    def set_search_album_title(self, term):
        self.search_album_title = term

    def set_filter_year(self, term):
        self.filter_year = term

    def set_filter_genre(self, term):
        self.filter_genre = term

    def set_filter_album_id(self, term):
        self.filter_album_id = term

    def set_filter_artist_id(self, term):
        self.filter_artist_id = term

    def set_order_by(self, field, direction="asc"):
        if (not field in self.order_by_fields or
            not direction in self.order_by_directions):
            return

        self.order_by_field = field
        self.order_by_direction = direction

    def get_default_result(self, result_type, page):
        search = {}
        if self.search_title is not None:
            value = self.search_title
            if value.find(" ") != -1:
                value = "(" + value + ")"
            search["title"] = value
        if self.search_artist_name is not None:
            value = self.search_artist_name
            if value.find(" ") != -1:
                value = "(" + value + ")"
            search["artist"] = value
        if self.search_album_title is not None:
            value = self.search_album_title
            if value.find(" ") != -1:
                value = "(" + value + ")"
            search["album"] = value
        if self.filter_genre is not None:
            genre = Genre.objects.all().filter(id=self.filter_genre)[0:1].get()
            value = genre.Name
            if value.find(" ") != -1:
                value = "(" + value + ")"
            search["genre"] = value
            search["genre_id"] = genre.id
        if self.filter_year is not None:
            search["year"] = str(self.filter_year)
        if self.search_term is not None:
            search["term"] = self.search_term

        return {
            "type": result_type,
            "page": page,
            "hasNextPage": False,
            "itemList": [],
            "order": [],
            "search": search,
        }

    def result_add_queue_and_favourite(self, song, dataset):
        if not self.user_id is None:
            try:
                queue = Queue.objects.get(Song=song)
                for user in queue.User.all():
                    if user.id == self.user_id:
                        dataset["queued"] = True
                        break
            except ObjectDoesNotExist:
                pass
            try:
                user = User.objects.get(id=self.user_id)
                Favourite.objects.get(Song=song, User=user)
                dataset["favourite"] = True
            except ObjectDoesNotExist:
                pass

        return dataset

    def source_set_order(self, object_list):
        if not self.order_by_field is None:
            field_name = self.order_by_fields.get(self.order_by_field)
            if self.order_by_direction == "desc":
                field_name = "-" + field_name

            return object_list.order_by(field_name)
        elif not self.order_by_default is None:
            order = []
            for key, value in self.order_by_default.items():
                order.append(value)

            object_list = object_list.order_by(*order)

        return object_list

    def result_set_order(self, result):
        result["order"] = []

        if not self.order_by_field is None:
            result["order"].append({
                "field": self.order_by_field,
                "direction": self.order_by_direction,
            })
        elif not self.order_by_default is None:
            for field, order in self.order_by_default.items():
                result["order"].append({
                    "field": field,
                    "direction": "desc" if order.startswith("-") else "asc",
                })

        return result

class songs(api_base):
    order_by_fields = {
        "title": "Title",
        "artist": "Artist__Name",
        "album": "Album__Title",
        "year": "Year",
        "genre": "Genre__Name",
        "length": "Length",
    }
    order_by_default = {
        "title": "Title",
    }

    def index(self, page=1):
        object_list = Song.objects.all()

        # searches
        if not self.search_term is None:
            object_list = object_list.filter(
                Q(Title__contains=self.search_term)
                |
                Q(Artist__Name__contains=self.search_term)
                |
                Q(Album__Title__contains=self.search_term)
            )
        if not self.search_title is None:
            object_list = object_list.filter(
                 Title__contains=self.search_title
             )
        if not self.search_artist_name is None:
            object_list = object_list.filter(
                 Artist__Name__contains=self.search_artist_name
             )
        if not self.search_album_title is None:
            object_list = object_list.filter(
                 Album__Title__contains=self.search_album_title
             )

        # filters
        if not self.filter_year is None:
            object_list = object_list.filter(
                 Year__exact=self.filter_year
             )
        if not self.filter_genre is None:
            object_list = object_list.filter(
                 Genre__exact=self.filter_genre
             )
        if not self.filter_album_id is None:
            object_list = object_list.filter(
                 Album__exact=self.filter_album_id
             )
        if not self.filter_artist_id is None:
            object_list = object_list.filter(
                 Artist__exact=self.filter_artist_id
             )

        # order
        object_list = self.source_set_order(object_list)

        # prepare result
        result = self.get_default_result("songs", page)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            dataset = {
                "id": item.id,
                "title": None,
                "artist": {
                    "id": None,
                    "name": None,
                },
                "album": {
                    "id": None,
                    "title": None,
                },
                "year": None,
                "genre": {
                    "id": None,
                    "name": None,
                },
                "length": None,
                "queued": False,
                "favourite": False,
            }
            if not item.Title is None:
                dataset["title"] = item.Title
            if not item.Artist is None:
                dataset["artist"]["id"] = item.Artist.id
                dataset["artist"]["name"] = item.Artist.Name
            if not item.Album is None:
                dataset["album"]["id"] = item.Album.id
                dataset["album"]["title"] = item.Album.Title
            if not item.Year is None:
                dataset["year"] = item.Year
            if not item.Genre is None:
                dataset["genre"]["id"] = item.Genre.id
                dataset["genre"]["name"] = item.Genre.Name
            if not item.Length is None:
                dataset["length"] = item.Length

            dataset = self.result_add_queue_and_favourite(item, dataset)
            result["itemList"].append(dataset)

        return result

    def getNextSong(self):
        # commit transaction to force fresh queryset result
        try:
            transaction.enter_transaction_management()
            transaction.commit()
        except BaseException:
            pass

        try:
            data = Queue.objects.all()
            data = data.annotate(VoteCount=Count("User"))
            data = data.annotate(MinCreated=Min("Created"))
            data = data.order_by("-VoteCount", "MinCreated")[0:1].get()
            self.addToHistory(data.Song, data.User)
            song_instance = data.Song
            data.delete()
        except ObjectDoesNotExist:
            try:
                song_instance = self.getRandomSongByPreferences()
                self.addToHistory(song_instance, None)
            except ObjectDoesNotExist:
                song_instance = Song.objects.order_by('?')[0:1].get()
                self.addToHistory(song_instance, None)

        # remove missing files
        if not os.path.exists(song_instance.Filename.encode('utf8')):
            Song.objects.all().filter(id=song_instance.id).delete()
            return self.getNextSong()

        return song_instance

    def getRandomSongByPreferences(self):
        artists = {}

        # get logged in users
        sessions = Session.objects.exclude(
            expire_date__lt=datetime.today()
        )
        for session in sessions.all():
            data = session.get_decoded()
            if not "_auth_user_id" in data:
                continue
            user_id = data["_auth_user_id"]

            # get newest favourites
            favourites = Favourite.objects.filter(User__id=user_id)[0:30]
            for favourite in favourites:
                if not favourite.Song.Artist.id in artists:
                    artists[favourite.Song.Artist.id] = 0
                artists[favourite.Song.Artist.id]+= 1

            # get last voted songs
            votes = History.objects.filter(User__id=user_id)[0:30]
            for vote in votes:
                if not vote.Song.Artist.id in artists:
                    artists[vote.Song.Artist.id] = 0
                artists[vote.Song.Artist.id]+= 1

        # nothing played and no favourites
        if not len(artists):
            raise ObjectDoesNotExist

        # calculate top artists
        from operator import itemgetter
        sorted_artists = sorted(
            artists.iteritems(),
            key=itemgetter(1),
            reverse=True
        )[0:30]
        artists = []
        for key in range(len(sorted_artists)):
            artists.append(sorted_artists[key][0])

        # get the 50 last played songs
        history = History.objects.all()[0:50]
        last_played = []
        for item in history:
            last_played.append(item.Song.id)

        # find a song not played recently
        song_instance = Song.objects.exclude(
            id__in=last_played
        ).filter(
            Artist__id__in=artists
        ).order_by('?')[0:1].get()
        return song_instance

    def addToHistory(self, song_instance, user_list):
        history_instance = History(
            Song=song_instance
        )
        history_instance.save()

        if user_list is not None and user_list.count() > 0:
            for user_instance in user_list.all():
                history_instance.User.add(user_instance)

    def skipCurrentSong(self):
        players = Player.objects.all()
        for player in players:
            try:
                os.kill(player.Pid, SIGABRT)
            except OSError:
                player.delete()

class history(api_base):
    order_by_fields = {
        "title": "Song__Title",
        "artist": "Song__Artist__Name",
        "album": "Song__Album__Title",
        "year": "Song__Year",
        "genre": "Song__Genre__Name",
        "created": "Created",
    }
    order_by_default = {
        "created": "-Created",
    }

    def index(self, page=1):
        object_list = History.objects.all()
        object_list = self.source_set_order(object_list)
        result = self.build_result(object_list, page)
        result = self.result_set_order(result)
        return result

    def build_result(self, object_list, page):
        # prepare result
        result = self.get_default_result("history", page)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            dataset = {
                "id": item.Song.id,
                "title": None,
                "artist": {
                    "id": None,
                    "name": None,
                },
                "album": {
                    "id": None,
                    "title": None,
                },
                "year": None,
                "genre": {
                    "id": None,
                    "name": None,
                },
                "queued": False,
                "favourite": False,
                "created": formats.date_format(
                    item.Created, "DATETIME_FORMAT"
                ),
                "votes": item.User.count(),
                "users": [],
            }
            if not item.Song.Title is None:
                dataset["title"] = item.Song.Title
            if not item.Song.Artist is None:
                dataset["artist"]["id"] = item.Song.Artist.id
                dataset["artist"]["name"] = item.Song.Artist.Name
            if not item.Song.Album is None:
                dataset["album"]["id"] = item.Song.Album.id
                dataset["album"]["title"] = item.Song.Album.Title
            if not item.Song.Year is None:
                dataset["year"] = item.Song.Year
            if not item.Song.Genre is None:
                dataset["genre"]["id"] = item.Song.Genre.id
                dataset["genre"]["name"] = item.Song.Genre.Name

            if not item.User.count() == 0:
                for user in item.User.all():
                    dataset["users"].append({
                        "id": user.id,
                        "name": user.get_full_name()
                    })

            dataset = self.result_add_queue_and_favourite(item.Song, dataset)
            result["itemList"].append(dataset)

        return result

    def getCurrent(self):
        item = History.objects.all()[0:1].get()
        createdTimestamp = time.mktime(item.Created.timetuple())
        dataset = {
            "id": item.Song.id,
            "title": None,
            "artist": {
                "id": None,
                "name": None,
            },
            "album": {
                "id": None,
                "title": None,
            },
            "year": None,
            "genre": {
                "id": None,
                "name": None,
            },
            "queued": False,
            "favourite": False,
            "created": formats.date_format(
                item.Created, "DATETIME_FORMAT"
            ),
            "votes": item.User.count(),
            "users": [],
            "remaining": createdTimestamp + item.Song.Length - int(time.time())
        }
        if not item.Song.Title is None:
            dataset["title"] = item.Song.Title
        if not item.Song.Artist is None:
            dataset["artist"]["id"] = item.Song.Artist.id
            dataset["artist"]["name"] = item.Song.Artist.Name
        if not item.Song.Album is None:
            dataset["album"]["id"] = item.Song.Album.id
            dataset["album"]["title"] = item.Song.Album.Title
        if not item.Song.Year is None:
            dataset["year"] = item.Song.Year
        if not item.Song.Genre is None:
            dataset["genre"]["id"] = item.Song.Genre.id
            dataset["genre"]["name"] = item.Song.Genre.Name

        return dataset

class history_my(history):
    order_by_fields = {
        "title": "Song__Title",
        "artist": "Song__Artist__Name",
        "album": "Song__Album__Title",
        "year": "Song__Year",
        "genre": "Song__Genre__Name",
        "created": "Created",
    }
    order_by_default = {
        "created": "-Created",
    }

    def index(self, page=1):
        object_list = History.objects.all().filter(User__id=self.user_id)
        object_list = self.source_set_order(object_list)
        result = self.build_result(object_list, page)

        result = self.result_set_order(result)
        result["type"] = "history/my"
        return result


class queue(api_base):
    order_by_fields = {
        "title": "Song__Title",
        "artist": "Song__Artist__Name",
        "album": "Song__Album__Title",
        "year": "Song__Year",
        "genre": "Song__Genre__Name",
        "created": "Created",
        "votes": "VoteCount",
    }
    order_by_default = {
        "votes": "-VoteCount",
        "created": "MinCreated",
    }

    def index(self, page=1):
        object_list = Queue.objects.all()
        object_list = object_list.annotate(VoteCount=Count("User"))
        object_list = object_list.annotate(MinCreated=Min("Created"))
        object_list = self.source_set_order(object_list)

        # prepare result
        result = self.get_default_result("queue", page)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            result["itemList"].append(self.get(item.Song.id))

        return result

    def get(self, song_id):
        song = Song.objects.get(id=song_id)
        item = Queue.objects.get(Song=song)

        result = {
            "id": item.Song.id,
            "title": None,
            "artist": {
                "id": None,
                "name": None,
            },
            "album": {
                "id": None,
                "title": None,
            },
            "year": None,
            "genre": {
                "id": None,
                "name": None,
            },
            "queued": False,
            "favourite": False,
            "created": formats.date_format(item.Created, "DATETIME_FORMAT"),
            "votes": item.User.count(),
            "users": [],
        }

        if not item.Song.Title is None:
            result["title"] = item.Song.Title
        if not item.Song.Artist is None:
            result["artist"]["id"] = item.Song.Artist.id
            result["artist"]["name"] = item.Song.Artist.Name
        if not item.Song.Album is None:
            result["album"]["id"] = item.Song.Album.id
            result["album"]["title"] = item.Song.Album.Title
        if not item.Song.Year is None:
            result["year"] = item.Song.Year
        if not item.Song.Genre is None:
            result["genre"]["id"] = item.Song.Genre.id
            result["genre"]["name"] = item.Song.Genre.Name

        if not item.User.count() == 0:
            for user in item.User.all():
                result["users"].append({"id": user.id, "name": user.get_full_name()})

        result = self.result_add_queue_and_favourite(item.Song, result)

        return result

    def add(self, song_id):
        song = Song.objects.get(id=song_id)
        user = User.objects.get(id=self.user_id)

        try:
            queue = Queue.objects.get(Song=song)
        except ObjectDoesNotExist:
            queue = Queue(
                Song=song
            )
            queue.save()
        queue.User.add(user)

        return song_id

    def remove(self, song_id):
        song = Song.objects.get(id=song_id)
        user = User.objects.get(id=self.user_id)

        queue = Queue.objects.get(Song=song)
        queue.User.remove(user)
        vote_count = queue.User.count()
        if not queue.User.count():
            queue.delete()

        return {
            "id": song_id,
            "count": vote_count,
        }


class favourites(api_base):
    order_by_fields = {
        "title": "Song__Title",
        "artist": "Song__Artist__Name",
        "album": "Song__Album__Title",
        "year": "Song__Year",
        "genre": "Song__Genre__Name",
        "created": "Created",
    }
    order_by_default = {
        "created": "-Created",
    }

    def index(self, page=1):
        object_list = Favourite.objects.all().filter(User__id=self.user_id)
        object_list = self.source_set_order(object_list)

        # prepare result
        result = self.get_default_result("favourites", page)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            result["itemList"].append(self.get(item.Song.id))

        return result

    def get(self, song_id):
        song = Song.objects.get(id=song_id)
        item = Favourite.objects.get(Song=song,User__id=self.user_id)

        result = {
            "id": item.Song.id,
            "title": None,
            "artist": {
                "id": None,
                "name": None,
            },
            "album": {
                "id": None,
                "title": None,
            },
            "year": None,
            "genre": {
                "id": None,
                "name": None,
            },
            "queued": False,
            "favourite": False,
            "created": formats.date_format(item.Created, "DATETIME_FORMAT"),
        }

        if not item.Song.Title is None:
            result["title"] = item.Song.Title
        if not item.Song.Artist is None:
            result["artist"]["id"] = item.Song.Artist.id
            result["artist"]["name"] = item.Song.Artist.Name
        if not item.Song.Album is None:
            result["album"]["id"] = item.Song.Album.id
            result["album"]["title"] = item.Song.Album.Title
        if not item.Song.Year is None:
            result["year"] = item.Song.Year
        if not item.Song.Genre is None:
            result["genre"]["id"] = item.Song.Genre.id
            result["genre"]["name"] = item.Song.Genre.Name

        result = self.result_add_queue_and_favourite(item.Song, result)

        return result

    def add(self, song_id):
        song = Song.objects.get(id=song_id)
        user = User.objects.get(id=self.user_id)

        favourite = Favourite(
            Song=song,
            User=user
        )
        favourite.save()

        return song_id

    def remove(self, song_id):
        song = Song.objects.get(id=song_id)
        user = User.objects.get(id=self.user_id)

        Favourite.objects.get(
            Song=song,
            User=user
        ).delete()

        return {
            "id": song_id,
        }


class recommendations(api_base):
    order_by_fields = {
        "title": "Song__Title",
        "artist": "Song__Artist__Name",
        "album": "Song__Album__Title",
        "year": "Song__Year",
        "genre": "Song__Genre__Name",
    }

    def index(self, page=1):
        user = User.objects.get(id=self.user_id)
        provider = recommendation_registry.get_provider_for_content(Song)
        #object_list = map(lambda rec: rec.object, provider.storage.get_recommendations_for_user(user, 25))
        object_list = provider.storage.get_recommendations_for_user(user, 25)
        object_list = self.source_set_order(object_list)

        # prepare result
        result = self.get_default_result("recommendations", page)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            result["itemList"].append(self.get(item.object.id))

        return result

    def get(self, song_id):
        item = Song.objects.get(id=song_id)

        result = {
            "id": item.id,
            "title": None,
            "artist": {
                "id": None,
                "name": None,
            },
            "album": {
                "id": None,
                "title": None,
            },
            "year": None,
            "genre": {
                "id": None,
                "name": None,
            },
            "queued": False,
            "favourite": False,
        }

        if not item.Title is None:
            result["title"] = item.Title
        if not item.Artist is None:
            result["artist"]["id"] = item.Artist.id
            result["artist"]["name"] = item.Artist.Name
        if not item.Album is None:
            result["album"]["id"] = item.Album.id
            result["album"]["title"] = item.Album.Title
        if not item.Year is None:
            result["year"] = item.Year
        if not item.Genre is None:
            result["genre"]["id"] = item.Genre.id
            result["genre"]["name"] = item.Genre.Name

        result = self.result_add_queue_and_favourite(item, result)

        return result


class artists(api_base):
    order_by_fields = {
        "artist": "Name",
    }
    order_by_default = {
        "artist": "Name",
    }

    def index(self, page=1):
        # prepare result
        result = self.get_default_result("artists", page)

        object_list = Artist.objects.all()
        object_list = self.source_set_order(object_list)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            dataset = {
                "id": item.id,
                "artist": item.Name,
            }

            result["itemList"].append(dataset)

        return result


class albums(api_base):
    order_by_fields = {
        "album": "Title",
    }
    order_by_default = {
        "album": "Title",
    }

    def index(self, page=1):
        # prepare result
        result = self.get_default_result("albums", page)

        object_list = Album.objects.all()
        object_list = self.source_set_order(object_list)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            dataset = {
                "id": item.id,
                "album": item.Title,
            }

            result["itemList"].append(dataset)

        return result


class genres(api_base):
    order_by_fields = {
        "genre": "Name",
    }
    order_by_default = {
        "genre": "Name",
    }

    def index(self, page=1):
        # prepare result
        result = self.get_default_result("genres", page)

        object_list = Genre.objects.all()
        object_list = self.source_set_order(object_list)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            dataset = {
                "id": item.id,
                "genre": item.Name,
            }

            result["itemList"].append(dataset)

        return result


class years(api_base):
    order_by_fields = {
        "year": "Year",
    }
    order_by_default = {
        "year": "Year"
    }

    def index(self, page=1):
        # prepare result
        result = self.get_default_result("years", page)

        object_list = Song.objects.values("Year").distinct()
        object_list = object_list.exclude(Year=None).exclude(Year=0)
        object_list = self.source_set_order(object_list)

        # get data
        paginator = Paginator(object_list, self.count)
        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return result

        result = self.result_set_order(result)
        result["hasNextPage"] = page_obj.has_next()
        for item in page_obj.object_list:
            dataset = {
                "year": item["Year"],
            }

            result["itemList"].append(dataset)

        return result


class players(api_base):
    def add(self, pid):
        player = Player(
            Pid=pid
        )
        player.save()

        return player.id

    def remove(self, pid):
        Player.objects.get(Pid=pid).delete()

        return {
            "pid": pid,
        }
