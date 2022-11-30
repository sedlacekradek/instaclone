from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func
from flask_login import current_user
from .search import add_to_index, remove_from_index, query_index
from datetime import datetime


# setting up many-to-many relationship for user-bookmarks
user_picture = db.Table("user_picture",
                        db.Column("user_id", db.Integer(), db.ForeignKey("user.id")),
                        db.Column("picture_id", db.Integer(), db.ForeignKey("picture.id"))
                        )

# setting up many-to-many relationship for followers (user-user)
followers = db.Table('followers',
                     db.Column('follower_id', db.Integer(), db.ForeignKey('user.id')),
                     db.Column('followed_id', db.Integer(), db.ForeignKey('user.id'))
                     )

# setting up many-to-many relationship for blocked users (user-user)
blocked = db.Table('blocked',
                   db.Column('blocked_id', db.Integer(), db.ForeignKey('user.id')),
                   db.Column('blocker_id', db.Integer(), db.ForeignKey('user.id'))
                   )


### SEARCHABLE CLASS ###
# implemented as per https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-xvi-full-text-search
class SearchableMixin(object):
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        # if no results
        if total == 0:
            return cls.query.filter_by(id=0), 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        # db.case to align elasticsearch IDs with object IDs
        return cls.query.filter(cls.id.in_(ids)).order_by(
            db.case(when, value=cls.id)), total

    @classmethod
    def before_commit(cls, session):
        # save changes into dictionary before commit
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    @classmethod
    def after_commit(cls, session):
        # update search index with before_commit changes
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                # creates new data
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                # if index already exists, it is updated with new data
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                # deletes data if user deleted
                remove_from_index(obj.__tablename__, obj)
        # clear _changes dictionary
        session._changes = None

    @classmethod
    def reindex(cls):
        # to index already created objects
        for obj in cls.query:
            add_to_index(cls.__tablename__, obj)


# db event listeners
db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)


### DB CLASSES ###
class User(db.Model, UserMixin, SearchableMixin):
    __searchable__ = ["username", "description"]
    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(), unique=True)
    username = db.Column(db.String(), unique=True)
    password = db.Column(db.String())
    description = db.Column(db.String(), default="no description filled in")
    avatar = db.Column(db.String(), default="/static/img/default-user.png")
    date_created = db.Column(db.DateTime(), default=func.now())
    pictures = db.relationship("Picture", backref="author", cascade="all,delete")
    stories = db.relationship("Story", backref="author", cascade="all,delete")
    comments = db.relationship("Comment", backref="author")
    likes = db.relationship("Like", backref="author", cascade="all,delete")
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')
    blocked = db.relationship(
        'User', secondary=blocked,
        primaryjoin=(blocked.c.blocked_id == id),
        secondaryjoin=(blocked.c.blocker_id == id),
        backref=db.backref('blocker', lazy='dynamic'), lazy='dynamic')
    notification_sent = db.relationship('Notification', foreign_keys='Notification.sender_id', backref='author',
                                        lazy='dynamic')
    notification_received = db.relationship('Notification', foreign_keys='Notification.recipient_id',
                                            backref='recipient', lazy='dynamic')
    last_notification_read_time = db.Column(db.DateTime())
    not_recommend = db.Column(db.Boolean(), default=False)
    messages_sent = db.relationship('UserMessage', foreign_keys='UserMessage.sender_id', backref='author',
                                    lazy='dynamic')
    messages_received = db.relationship('UserMessage', foreign_keys='UserMessage.recipient_id', backref='recipient',
                                        lazy='dynamic')
    last_message_read_time = db.Column(db.DateTime())
    last_message_sent_time = db.Column(db.DateTime(), server_default=func.now())

    def new_notifications(self):
        # returns number of unread notifications, function called by htmx every 60s and shows notification if > 0
        last_read_time = self.last_notification_read_time or datetime(1900, 1, 1)
        return Notification.query.filter_by(recipient=self).filter(Notification.timestamp > last_read_time,
                                                                   Notification.author != self).count()

    def new_messages(self):
        # returns unread messages, function called by htmx every 5s and shows notification if True
        return UserMessage.query.filter_by(recipient_id=self.id).filter_by(seen=False).all()


class UserMessage(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    sender_id = db.Column(db.Integer(), db.ForeignKey("user.id"))
    recipient_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    body = db.Column(db.String())
    timestamp = db.Column(db.DateTime(), index=True, default=func.now())
    seen = db.Column(db.Boolean(), default=False)


class Picture(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    description = db.Column(db.String())
    location = db.Column(db.String(), default=None)
    date_created = db.Column(db.DateTime(), default=func.now())
    author_id = db.Column(db.Integer(), db.ForeignKey("user.id"))
    private = db.Column(db.Boolean, default=False)
    file = db.Column(db.String())
    bookmarked_by = db.relationship("User", secondary=user_picture, backref="bookmarks")
    likes = db.relationship("Like", backref="picture", cascade="all,delete")
    comments = db.relationship("Comment", backref="picture", cascade="all,delete")

    def mutual_likes(self):
        """
        Returns string of who liked the picture in format: "Liked by friend1, friend2 and XX other user(s)."

        :return: String to be shown to the user.
        """
        mutual_likes_list = []
        for like in self.likes:
            user = User.query.filter_by(id=like.author_id).first_or_404()
            # if liked by current_user
            if user == current_user:
                mutual_likes_list.insert(0, "you")
            # if liked by followed users
            if user in current_user.followed and user != current_user:
                mutual_likes_list.append(user.username)
        # like_number = total number of likes - likes by followed users
        like_number = len(self.likes) - len(mutual_likes_list[0:3])
        # liked only by friends
        if mutual_likes_list and like_number < 1:
            return f"Liked by {' and '.join(mutual_likes_list[0:3])}"
        # if liked by more than 3 users a some of them are friends
        if mutual_likes_list and like_number > 0:
            return f"Liked by {' and '.join(mutual_likes_list[0:3])} and {like_number} other user(s)"
        # if no friend liked post
        if not mutual_likes_list:
            return f"Liked by {len(self.likes)} user(s)"


class Comment(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    text = db.Column(db.String())
    date_created = db.Column(db.DateTime(), default=func.now())
    author_id = db.Column(db.Integer(), db.ForeignKey("user.id"))
    picture_id = db.Column(db.Integer(), db.ForeignKey("picture.id"))
    deleted = db.Column(db.Boolean(), default=False)
    likes = db.relationship("Like", backref="comment", cascade="all,delete")


class Like(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    author_id = db.Column(db.Integer(), db.ForeignKey("user.id"))
    comment_id = db.Column(db.Integer(), db.ForeignKey("comment.id"), default=None)
    picture_id = db.Column(db.Integer(), db.ForeignKey("picture.id"), default=None)
    date_created = db.Column(db.DateTime(), default=func.now())


class Story(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    date_created = db.Column(db.DateTime(), default=func.now())
    author_id = db.Column(db.Integer(), db.ForeignKey("user.id"))
    time_span = db.Column(db.Integer())
    file = db.Column(db.String())


class Notification(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    sender_id = db.Column(db.Integer(), db.ForeignKey("user.id"))
    recipient_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    body = db.Column(db.String())
    type = db.Column(db.String())
    link = db.Column(db.String())
    timestamp = db.Column(db.DateTime(), index=True, default=func.now())