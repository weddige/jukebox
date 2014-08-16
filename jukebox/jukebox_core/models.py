# -*- coding: UTF-8 -*-

from django.db import models
from django.contrib.auth.models import User
from django.contrib.syndication.views import Feed
import time
from recommends.providers import recommendation_registry, RecommendationProvider

class Artist(models.Model):
    class Meta:
        ordering = ['Name']

    def __unicode__(self):
        return "%s" % self.Name

    Name = models.CharField(max_length=200)


class Genre(models.Model):
    class Meta:
        ordering = ['Name']

    def __unicode__(self):
        return "%s" % self.Name

    Name = models.CharField(max_length=200)


class Album(models.Model):
    class Meta:
        ordering = ['Title']

    def __unicode__(self):
        return "%s" % self.Title

    Title = models.CharField(max_length=200)


class Song(models.Model):
    class Meta:
        ordering = ['Title', 'Artist', 'Album']

    def __unicode__(self):
        return "%s - %s" % (self.Artist.Name, self.Title)

    Artist = models.ForeignKey(Artist)
    Album = models.ForeignKey(Album, null=True)
    Genre = models.ForeignKey(Genre, null=True)
    Title = models.CharField(max_length=200)
    Year = models.IntegerField(null=True)
    Length = models.IntegerField()
    Filename = models.CharField(max_length=1000)


class Queue(models.Model):
    Song = models.ForeignKey(Song, unique=True)
    User = models.ManyToManyField(User)
    Created = models.DateTimeField(auto_now_add=True)


class Favourite(models.Model):
    class Meta:
        unique_together = ("Song", "User")
        ordering = ['-Created']

    Song = models.ForeignKey(Song)
    User = models.ForeignKey(User)
    Created = models.DateTimeField(auto_now_add=True)


class History(models.Model):
    class Meta:
        ordering = ['-Created']

    Song = models.ForeignKey(Song)
    User = models.ManyToManyField(User, null=True)
    Created = models.DateTimeField(auto_now_add=True)


class Player(models.Model):
    Pid = models.IntegerField()


class QueueFeed(Feed):
    title = "Jukebox Queue Feed"
    link = "/queue/"
    description = "Top song in the queue"

    def items(self):
        return Queue.objects.all()[:1]

    def item_title(self, item):
        return item.Song.Title


    def item_description(self, item):
        return unicode(item.Song.Title) + " by " + \
                unicode(item.Song.Artist) + " from " + \
                unicode(item.Song.Album)


    def item_link(self, item):
        # Not sure what to do with url as there isn't any unque url for song
        return "/queue/#" + unicode(int(round(time.time() * 1000)))

class RecommendationsProvider(RecommendationProvider):
    def get_users(self):
        return User.objects.filter(is_active=True)

    def get_items(self):
        return Song.objects.all()

    def get_ratings(self, obj):
        return Favourite.objects.filter(Song=obj)

    def get_rating_score(self, rating):
        return 1

    def get_rating_user(self, rating):
        return rating.User

    def get_rating_item(self, rating):
        return rating.Song

recommendation_registry.register(Favourite, [Song], RecommendationsProvider)
