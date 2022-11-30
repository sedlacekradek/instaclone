from flask import Blueprint, render_template, request, flash, redirect, url_for, g
from flask_login import login_required, current_user
from .models import User, Picture, Comment, Like, Story, Notification, UserMessage
from . import db, mail
import os
from flask_mail import Message
from werkzeug.urls import url_parse
from re import search as searchtext
import datetime as dt
from operator import itemgetter
from .forms import UploadForm, SettingsForm, CommentForm, StoryForm, DeleteForm, SearchForm, MessageForm
from .helpers import (
    upload_file,
    follow_user,
    followed_posts,
    recommended_follow_you,
    recommended_by_followed,
    followed_stories,
    delete_user,
    block_user,
    block_guard,
    get_location,
    mark_as_seen
)


ADMIN = "sedlacek.radek@email.cz"
views = Blueprint("views", __name__)


### BEFORE REQUEST ###
@views.before_app_request
def before_request():
    if current_user.is_authenticated:
        g.search_form = SearchForm()
        g.notifications_received = current_user.notification_received.order_by(Notification.timestamp.desc())


### CUSTOM PAGINATION ###
@views.route('/load-page/<int:id>/<int:page>')
@login_required
def load_page(id, page):
    # pagination function called by HTMX every 6 pictures
    # loaded pictures sliced in jinja [page:page+6]
    # each iteration the page value is increased by 6
    new_page = page + 6
    # if function called from homepage
    if url_parse(request.referrer).path in ("/", "/home"):
        pictures = followed_posts()
        return render_template("home-feed.html", pictures=pictures, page=new_page)
    # if function called from profile view
    if searchtext("profile", url_parse(request.referrer).path):
        user = User.query.filter_by(id=id).first_or_404()
        pictures = Picture.query.filter_by(author_id=id).order_by(Picture.date_created.desc()).all()
    # if function called from bookmarks view
    if searchtext("bookmarked", url_parse(request.referrer).path):
        user = User.query.filter_by(id=id).first_or_404()
        pictures = current_user.bookmarks
    return render_template("gallery-div.html", pictures=pictures, user=user, page=new_page)


### SEARCH ###
@views.route('/search')
@login_required
def search():
    # get page if next/prev url buttons
    page = request.args.get('page', 1, type=int)
    # calls class method
    results, total = User.search(g.search_form.q.data, page, 8)  # 8 results per page
    next_url = url_for('views.search', q=g.search_form.q.data, page=page + 1) if total > page * 8 else None
    prev_url = url_for('views.search', q=g.search_form.q.data, page=page - 1) if page > 1 else None
    return render_template('search.html', results=results, next_url=next_url, prev_url=prev_url)


### MAIN PAGE ###
@views.route("/")
@views.route("/home")
@login_required
def home():
    """
    Renders a page with:
    1) feed of followed posts with pagination through load_page function
    2) user recommendations -  followed_by_friends, follows_you
    3) feed of stories
    """
    return render_template("home.html",
                           pictures=followed_posts(),
                           page=0,
                           followed_by_friends=recommended_by_followed(),
                           follows_you=recommended_follow_you(),
                           stories=followed_stories())


@views.route("/disclaimer")
@login_required
def disclaimer():
    """
    Renders disclaimer and attribution page.
    """
    return render_template("disclaimer.html")


@views.route("/api-docs")
@login_required
def api_docs():
    """
    Renders api documentation page.
    """
    return render_template("api-docs.html")


### PROFILE PAGE ###
@views.route("/profile/<int:id>")
@login_required
def profile(id):
    """
    Renders a page with user pictures with pagination through load_page function.
    """
    user = User.query.filter_by(id=id).first_or_404()
    pictures = Picture.query.filter_by(author_id=id).order_by(Picture.date_created.desc()).all()
    # active parameter says what UI elements should be marked as active
    return render_template("profile.html", pictures=pictures, user=user, active=("profile", "gallery"), page=0)


@views.route("/bookmarked/<int:id>")
@login_required
def bookmarked(id):
    """
    Renders a page with bookmarked pictures with pagination through load_page function.
    """
    user = User.query.filter_by(id=id).first_or_404()
    if current_user != user:
        flash("You cannot view saved posts of other users", category="error")
        return redirect(url_for("views.home"))
    # active parameter says what UI elements should be marked as active
    return render_template("profile.html", pictures=current_user.bookmarks, user=user, active=("profile", "bookmarks"),
                           page=0)


### PICTURE FUNCTIONS ###
@views.route("/picture/<int:id>", methods=['GET', 'POST'])
@login_required
def view_picture(id):
    """
    Renders page with picture view and comments.
    """
    picture = Picture.query.filter_by(id=id).first_or_404()
    if block_guard(picture.author_id):
        return redirect(url_for("views.home"))
    form = CommentForm()
    # if users posts a comment
    if form.validate_on_submit():
        comment = Comment(text=form.text.data, author_id=current_user.id, picture_id=picture.id)
        db.session.add(comment)
        # send a new_notification if commenting pictures of other users
        if picture.author != current_user:
            new_notification = Notification(sender_id=current_user.id,
                                            recipient_id=picture.author_id,
                                            type="comment",
                                            body=f"{current_user.username} commented your post.",
                                            link=f'{url_for("views.view_picture", id=picture.id)}'
                                            )
            db.session.add(new_notification)
        db.session.commit()
        flash("Comment has been posted", category="success")
        return redirect(url_for("views.view_picture", id=picture.id))
    return render_template("picture.html", form=form, picture=picture)


@views.route("/like-picture/<int:id>")
@login_required
def like_picture(id):
    """
    Creates or deletes a Like object and returns an updated <div>.
    """
    picture = Picture.query.filter_by(id=id).first_or_404()
    like = Like.query.filter_by(author_id=current_user.id, picture_id=id).first()
    # if picture already liked, delete the like
    if like:
        db.session.delete(like)
        db.session.commit()
    # if picture not liked, create a new like object
    else:
        like = Like(author_id=current_user.id, picture_id=id)
        db.session.add(like)
        # if liking pictures of other users create new_notification
        if picture.author != current_user:
            new_notification = Notification(sender_id=current_user.id,
                                            recipient_id=picture.author_id,
                                            type="like",
                                            body=f"{current_user.username} liked your post.",
                                            link=f'{url_for("views.view_picture", id=picture.id)}'
                                            )
            db.session.add(new_notification)
        db.session.commit()
    # if function called from homepage
    if url_parse(request.referrer).path in ("/", "/home"):
        return render_template("post-footer.html", picture=picture)
    # if function called from pic view
    return render_template("picture-like.html", picture=picture)


@views.route("/bookmark/<int:id>")
@login_required
def bookmark_picture(id):
    """
    Adds or removes a Picture object to current_user's bookmarks and returns an updated <div> to HTMX call.
    """
    picture = Picture.query.filter_by(id=id).first_or_404()
    if picture in current_user.bookmarks:
        current_user.bookmarks.remove(picture)
    else:
        current_user.bookmarks.append(picture)
    db.session.commit()
    # if function called from homepage
    if url_parse(request.referrer).path in ("/", "/home"):
        return render_template("post-footer.html", picture=picture)
    # if function called from pic view
    return render_template("picture-bookmark.html", picture=picture)


@views.route("/like-comment/<int:id>")
@login_required
def like_comment(id):
    """
    Creates or deletes a Like object and returns an updated <div> to HTMX call.
    """
    comment = Comment.query.filter_by(id=id).first_or_404()
    like = Like.query.filter_by(author_id=current_user.id, comment_id=id).first()
    # if comment already liked, delete the like
    if like:
        db.session.delete(like)
        db.session.commit()
    # if comment not liked yet, create a new like object
    else:
        like = Like(author_id=current_user.id, comment_id=id)
        db.session.add(like)
        db.session.commit()
    return render_template("comment-like.html", comment=comment)


@login_required
@views.route("/change-privacy/<int:id>")
def change_privacy(id):
    """
    Change the privacy parameter of a picture.
    """
    picture = Picture.query.filter_by(id=id).first_or_404()
    if current_user != picture.author:
        flash("Only the author can change this.", category="error")
        return redirect(url_for("views.view_picture", id=picture.id))
    if picture.private:
        picture.private = False
    else:
        picture.private = True
    db.session.commit()
    return redirect(url_for("views.view_picture", id=picture.id))


@views.route("/picture-delete/<int:id>")
@login_required
def delete_picture(id):
    """
    Delete picture - set to 'cascade="all,delete" to delete comments, likes when picture object deleted.
    """
    picture = Picture.query.filter_by(id=id).first_or_404()
    if current_user.id != picture.author.id:
        flash("Only the author can delete this.", category="error")
    else:
        # delete file
        os.remove(f"web/{picture.file}")
        # delete object
        db.session.delete(picture)
        db.session.commit()
        flash("Picture deleted.", category="success")
    pictures = Picture.query.filter_by(author_id=current_user.id).all()
    return render_template("profile.html", pictures=pictures, user=current_user, active=("profile", "gallery"), page=0)


@views.route("/report-picture/<int:id>", methods=["GET", "POST"])
@login_required
def report_picture(id):
    """
    Send info to admin that User X reported Picture Y
    """
    picture = Picture.query.filter_by(id=id).first_or_404()
    msg = Message(
        subject="Instaclone - picture reported",
        body=f"Picture {picture.id} was reported by user {current_user.id}",
        recipients=[ADMIN]
    )
    mail.send(msg)
    flash('Mail has been sent.', category="success")
    return redirect(url_for("views.home"))


### UPLOAD PAGE ###
@views.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """
    Renders page to upload a new picture.
    """
    form = UploadForm()
    location = ""
    if form.validate_on_submit():
        # if user wants to share location, get location string
        if form.location.data is True:
            location = get_location()
        # create a new object
        filepath = upload_file(form.file.data, current_user.username)
        picture = Picture(description=form.description.data, location=location,
                          private=form.private.data, file=filepath, author=current_user)
        db.session.add(picture)
        db.session.commit()
        return redirect(url_for("views.profile", id=current_user.id, active=("profile", "gallery")))
    return render_template('upload-pictures.html', form=form, active="upload")


@views.route("/loading-gif")
@login_required
def loading_gif():
    """
    Renders a loading animation when uploading a picture.
    """
    return render_template('loading-gif.html')


### SETTINGS PAGE ###
@views.route("/settings", methods=['GET', 'POST'])
@login_required
def settings():
    """
    Renders page with user settings. Users can also delete their entire profiles from this page.

    more info about using two wtforms on one page:
    https://stackoverflow.com/questions/18290142/multiple-forms-in-a-single-page-using-flask-and-wtforms
    """
    # prefilled form to adjust settings
    form = SettingsForm(description=current_user.description,
                        not_recommend=current_user.not_recommend)
    # form to confirm deletion of the profile, form is located in a modal
    delete_form = DeleteForm()
    # 1) if SettingsForm submitted
    if form.submit.data and form.validate_on_submit():
        # if new avatar uploaded
        if form.file.data:
            filename = upload_file(file=form.file.data, user_name=current_user.username)
            current_user.avatar = filename
        current_user.description = form.description.data
        current_user.not_recommend = form.not_recommend.data
        db.session.commit()
        return redirect(url_for("views.profile", id=current_user.id, active=("profile", "gallery")))
    # 2) if DeleteForm submitted
    if delete_form.delete.data and delete_form.validate():
        flash("The profile has been deleted.", category="success")
        delete_user(current_user)
        return redirect(url_for("views.goodbye"))
    if delete_form.errors:
        # modal automatically closes after submission, even if an error was raised by the form and the error is not
        # visible; code below shows WTForm error from the modal as a flash message
        for field, errors in delete_form.errors.items():
            flash(', '.join(errors), category="error")
    return render_template('settings.html', form=form, delete_form=delete_form)


@views.route("/goodbye")
def goodbye():
    """
    Renders a page for users who deleted their accounts.
    """
    return render_template('goodbye.html')


### MESSAGE FUNCTIONS ###
@views.route("/refresh-messages/<int:id>")
@login_required
def refresh_messages(id):
    """
    Refreshes messages in the chat window if either user sent a message in the last 2 seconds or returns 204 No Content.
    Function is called by HTMX every 0.5s. Messages are paginated through load_messages function.
    """
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    two_sec_ago = now - dt.timedelta(seconds=2)
    user = User.query.filter_by(id=id).first_or_404()
    if current_user.last_message_sent_time > two_sec_ago or user.last_message_sent_time > two_sec_ago:
        messages_sent = UserMessage.query.filter_by(sender_id=current_user.id).filter_by(recipient_id=user.id)
        messages_received = UserMessage.query.filter_by(recipient_id=current_user.id).filter_by(sender_id=user.id)
        mark_as_seen(messages_received)
        messages_all = messages_sent.union(messages_received).all()
        return render_template('messages-div.html', user=user, messages=messages_all, page=0)
    return ('', 204)


@views.route("/load-messages/<int:id>/<int:page>")
@login_required
def load_messages(id, page):
    """
    Custom pagination function for chat messages. Function is called by HTMX if user clicks on "load previous" button
    and shows 15 older messages to the user by updating the "page" variable. Messages are sliced in Jinja: [-page-30:]
    """
    new_page = page + 15
    user = User.query.filter_by(id=id).first_or_404()
    messages_sent = UserMessage.query.filter_by(sender_id=current_user.id).filter_by(recipient_id=user.id)
    messages_received = UserMessage.query.filter_by(recipient_id=current_user.id).filter_by(sender_id=user.id)
    messages_all = messages_sent.union(messages_received).all()
    return render_template('messages-div.html', user=user, messages=messages_all, page=new_page)


@views.route("/chat-central")
@login_required
def chat_central():
    """
    Renders a page with all users(=contacts) with chats started with current_user.
    """
    contacts = {}
    # find all messages sent by current_user, for each recipient save the latest message (the highest ID)
    for message in current_user.messages_sent:
        contacts[message.recipient] = message.id
        print(contacts)
    # find all messages received by user
    for message in current_user.messages_received:
        # keep only latest message from one message.author
        if message.author not in contacts:
            contacts[message.author] = message.id
        elif contacts[message.author] < message.id:
            contacts[message.author] = message.id
        else:
            pass
    # sort messages by message.id from newest to oldest, users will see most recent messages on top
    sorted_contacts = dict(sorted(contacts.items(), key=itemgetter(1), reverse=True))
    return render_template('chat-central.html', contacts=sorted_contacts)


@views.route("/chat/<int:id>", methods=["POST", "GET"])
@login_required
def chat(id):
    """
    Renders a chatting window.
    """
    form = MessageForm()
    user = User.query.filter_by(id=id).first_or_404()
    messages_sent = UserMessage.query.filter_by(sender_id=current_user.id).filter_by(recipient_id=user.id)
    messages_received = UserMessage.query.filter_by(recipient_id=current_user.id).filter_by(sender_id=user.id)
    # mark received messages as seen
    mark_as_seen(messages_received)
    # combine sent and received messages
    messages_all = messages_sent.union(messages_received).all()
    if form.validate_on_submit() and block_guard(id) is False:
        # create a new message object
        message = UserMessage(author=current_user, recipient=user, body=form.text.data)
        db.session.add(message)
        # update time of last sent message, used in refresh_messages function
        current_user.last_message_sent_time = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        db.session.commit()
        # clear the form input
        form.text.data = ""
    return render_template('chat-window.html', form=form, user=user, messages=messages_all, page=0)


@views.route('/messages')
@login_required
def messages():
    """
    answers to htmx call with updated navbar message icon
    """
    return render_template('new-messages.html')


### STORIES ###
@views.route('/upload-story', methods=['GET', 'POST'])
@login_required
def upload_story():
    """
    Renders page to upload a new story.
    """
    form = StoryForm()
    if form.validate_on_submit():
        filepath = upload_file(form.file.data, current_user.username)
        story = Story(time_span=form.time_span.data, file=filepath, author=current_user)
        db.session.add(story)
        db.session.commit()
        return redirect(url_for("views.home"))
    return render_template('upload-story.html', form=form)


@views.route('/load-modal/<int:id>')
@login_required
def load_modal(id):
    """
    Loads modal with a story. The ID parameter does not mark Story.id in the database, but the Jinja loop.index
    starting from 0. E.g. if user clicks on the second story from left, the ID will be always 1 no matter the
    Story.id.
    """
    stories = followed_stories()
    _story = stories[id]
    if block_guard(_story.author_id):
        return redirect(url_for("views.home"))
    return render_template('story-modal.html', active_story=id, stories=stories)


### BLOCKING USERS ###
@views.route("/blocked")
@login_required
def blocked():
    """
    Renders a page with all blocked users.
    """
    return render_template('blocked.html')


@views.route("/block/<user_id>")
@login_required
def blocked_update(user_id):
    """
    Blocks or unblocks a user and returns an updated <div> to HTMX call.
    """
    block_user(user_id)
    user = User.query.filter_by(id=user_id).first_or_404()
    # if function called from profile view
    if searchtext("profile", url_parse(request.referrer).path):
        return render_template("profile-header.html", user=user)
    # if function called from blocked users page
    if searchtext("blocked", url_parse(request.referrer).path):
        return render_template("blocked-div.html", user=user)


### FOLLOWERS ###
@views.route("/follow/<user_id>/<int:id>")
@login_required
def followers_update(user_id, id):
    """
    Follows or unfollows a user and returns an updated <div>
    """
    if block_guard(user_id):
        return redirect(url_for("views.home"))
    follow_user(user_id)
    # notification sent to the followed user
    new_notification = Notification(sender_id=current_user.id,
                                    recipient_id=user_id,
                                    type="follow",
                                    body=f"{current_user.username} started following you.",
                                    link=f'{url_for("views.profile", id=current_user.id)}'
                                    )
    db.session.add(new_notification)
    db.session.commit()
    # if function called from profile view
    if searchtext("bookmarked", url_parse(request.referrer).path):
        user = User.query.filter_by(id=id).first_or_404()
        return render_template("profile-header.html", user=user, active=("profile", "bookmarks"))
    # if function called from profile view
    if searchtext("profile", url_parse(request.referrer).path):
        user = User.query.filter_by(id=id).first_or_404()
        return render_template("profile-header.html", user=user, active=("profile", "gallery"))
    # if function called from pic view
    if searchtext("picture", url_parse(request.referrer).path):
        picture = Picture.query.filter_by(id=id).first_or_404()
        return render_template("picture-followers-div.html", picture=picture)
    # if function called from homepage view
    if url_parse(request.referrer).path in ("/", "/home"):
        picture = Picture.query.filter_by(id=id).first_or_404()
        return render_template("post-footer.html", picture=picture)


### NOTIFICATIONS ###
@views.route('/notifications/<status>')
@login_required
def notification(status):
    """
    HTMX calls this function every 60 s to check for new notifications. Function returns an updated <div> which
    automatically calls User.new_notifications(). When user clicks to see their notifications, the function is called
    with status "read" and the last_notification_read_time of the current user is updated.
    """
    if status == "read":
        current_user.last_notification_read_time = dt.datetime.now(dt.timezone.utc)
        db.session.commit()
        return render_template('notification-icon.html')
    return render_template('notifications.html')