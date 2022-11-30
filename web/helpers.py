from werkzeug.utils import secure_filename
import uuid
import os
from . import db
from .models import User, Picture, followers, Story
from flask_login import current_user
from random import shuffle
import datetime as dt
import shutil
from flask import flash, request
import requests
import tinify


tinify.key = os.getenv("YOUR_API_KEY")


### UPLOADING ###
def get_location():
    """
    Gets current location data from user's IP using ip-api.com

    :return: Returns string with user location or empty string on error.
    """
    try:
        _ip_addr = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        # if run locally
        if _ip_addr == "127.0.0.1":
            ip_addr = os.getenv("MY_IP")
        # if deployed
        else:
            ip_addr = _ip_addr.split(",")[1].replace(' ', '')
        response = requests.get(f"http://ip-api.com/json/{ip_addr}?fields=country,regionName,city")
        data = response.json()
        location = f"{data['country'], data['regionName']}".replace('(', '').replace(')', '').replace("'", '')
    except:
        return ""
    return location


def upload_file(file, user_name):
    """
    Saves a picture file uploaded by the user and returns string with the filepath. The file name is hashed to allow
    uploading multiple files with the same name. Pictures are compressed using tinify api.

    :param file: (werkzeug.datastructures.FileStorage) A file uploaded by the user
    :param user_name: Name of the user under which the file will be stored
    :return: String with the filepath: f'/static/uploads/{user_name}/{filename}
    """
    salt = str(uuid.uuid4())
    filename = f"{salt}{secure_filename(file.filename)}"
    filepath = f'web/static/uploads/{user_name}'
    save_path = f"{filepath}/{filename}"
    browser_path = f'/static/uploads/{user_name}/{filename}'
    if not os.path.exists(filepath):
        os.makedirs(filepath)
    file.save(save_path)
    # image compression
    try:
        source = tinify.from_file(save_path)
        source.to_file(save_path)
    except tinify.AccountError:
        pass
    return browser_path


### BLOCKING USERS ###
def block_user(user_id):
    """
    Blocks or unblocks a user. Removes mutual following when user is blocked.

    :param user_id: ID of the user to be (un)blocked.
    :return: True if successful.
    """
    user = User.query.filter_by(id=user_id).first_or_404()
    if user in current_user.blocked:
        current_user.blocked.remove(user)
    else:
        current_user.blocked.append(user)
        # remove myself from the followed of blocked user
        if current_user in user.followed:
            user.followed.remove(current_user)
        # remove user from my followed
        if user in current_user.followed:
            current_user.followed.remove(user)
    db.session.commit()
    return True


def block_guard(user_id):
    """
    Check if current_user and target user have one another in the blocked users list.

    :param user_id: ID of the target user.
    :return: Returns True if either user is blocked and flashes a message. Else, returns False.
    """
    user = User.query.filter_by(id=user_id).first_or_404()
    if current_user in user.blocked:
        flash("This has blocked you.", category="error")
        return True
    if user in current_user.blocked:
        flash("You have blocked this user.", category="error")
        return True
    return False


### FOLLOWING ###
def follow_user(user_id):
    """
    Follows or unfollows a user.

    :param user_id: ID of the user to be (un)followed.
    :return: True if successful.
    """
    user = User.query.filter_by(id=user_id).first_or_404()
    if user in current_user.followed:
        current_user.followed.remove(user)
    else:
        current_user.followed.append(user)
    db.session.commit()
    return True


def followed_posts():
    """
    Provides main page feed of pictures for current_user.

    :return: Query result of pictures for the current user's main page feed.
    """
    # posts of followed users
    # query below explained here: https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-viii-followers
    followed = Picture.query.join(
        followers, (followers.c.followed_id == Picture.author_id)).filter(
        followers.c.follower_id == current_user.id)
    # user's own pictures
    own = Picture.query.filter_by(author_id=current_user.id)
    # combine 2 queries
    return followed.union(own).order_by(Picture.date_created.desc()).all()


def followed_stories():
    """
    Provides main page feed of stories for current_user.

    :return: Query result of stories for the current user's main page feed.
    """
    # stories of followed users
    followed = Story.query.join(
        followers, (followers.c.followed_id == Story.author_id)).filter(
        followers.c.follower_id == current_user.id)
    # current_user's stories
    own = Story.query.filter_by(author_id=current_user.id)
    # combine 2 queries
    combine = followed.union(own).order_by(Story.date_created.desc()).all()
    # check if story should be shown according to its time_span
    stories = []
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for story in combine:
        # how many hours ago posted and compare with timespan
        posted_ago = now - story.date_created
        posted_ago_hours = posted_ago.total_seconds() / 3600
        # if within timespan - show to user
        if posted_ago_hours < story.time_span:
            stories.append(story)
        # if not, delete story
        else:
            # delete file
            os.remove(f"web/{story.file}")
            # delete object
            db.session.delete(story)
            db.session.commit()
    # return stories, set limit to 21 for edge cases
    return stories[0:21]


def recommended_follow_you():
    """
    Compares list of current_user.followers with current_user.followed and returns a list of users that follow
    current user but are not followed back and their not_recommend setting is False.

    :return: Shuffled list of users that follow current user and are not followed back.
    """
    follows_you = []
    # find users that meet conditions
    for follower in current_user.followers:
        if follower not in current_user.followed and follower.not_recommend is False:
            follows_you.append(follower)
    # shuffle result
    shuffle(follows_you)
    return follows_you


def recommended_by_followed():
    """
    Finds all users that current_user does not follow. Find which of these users are followed by users that
    current_user follows ("mutual friends logic"). Creates a tuple of (user, mutual friends).

    :return: Shuffled list of tuples [(recommended_user, [mutual_friend_X, mutual_friend_Y, ...]), (...[...])]
    """
    friends_follow = []
    # find all users that current_user does not follow
    not_followed_users = User.query.filter(~User.id.in_([followed.id for followed in current_user.followed])).all()
    # find "mutual friends"
    for user in not_followed_users:
        # do not include 1) current_user 2) blocked users 3) users that block current_user 4) users with not_recommend True
        if user != current_user and current_user not in user.blocked and user not in current_user.blocked and user.not_recommend is False:
            # find "mutual friends" by intersecting current_user.followed and user.followers
            common_followed = current_user.followed.intersect(user.followers).all()
            if common_followed:
                # append the list with (recommended_user, [mutual_friend_X, mutual_friend_Y, ...]
                friends_follow.append((user, common_followed))
    # shuffle result
    shuffle(friends_follow)
    return friends_follow


### MICS ###
def delete_user(user):
    # delete files
    try:
        shutil.rmtree(f"web/static/uploads/{user.username}")
    except FileNotFoundError:
        pass
    # delete object
    db.session.delete(user)
    db.session.commit()
    return True


def mark_as_seen(messages_received):
    """
    Changes the "seen" status of all given messages to True

    :param messages_received: Query object of all messages that should be checked.
    :return: Returns True if successful.
    """
    not_seen = messages_received.filter_by(seen=False).all()
    for message in not_seen:
        message.seen = True
    db.session.commit()
    return True