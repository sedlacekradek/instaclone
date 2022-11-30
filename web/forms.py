from flask_wtf import FlaskForm
from wtforms.validators import DataRequired, Length, Email, EqualTo
from wtforms import ValidationError
from .models import User
from flask_wtf.file import FileField, FileAllowed
from flask_login import current_user
from flask import request
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    EmailField,
    SelectField,
    TextAreaField,
    BooleanField,
)


### AUTH FORMS ###
class RegistrationForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Length(5, 64), Email()], render_kw={"placeholder": "Email"})
    name = StringField('Name', validators=[DataRequired(), Length(2, 64)], render_kw={"placeholder": "Name"})
    password = PasswordField('Password', validators=[DataRequired(), EqualTo(fieldname='password_repeat',
                                                                             message='Passwords must match.')],
                             render_kw={"placeholder": "Set Password"})
    password_repeat = PasswordField('Confirm Password', validators=[DataRequired()],
                                    render_kw={"placeholder": "Confirm Password"})
    submit = SubmitField('Sign Up')

    # custom validator - raise error if mail already used
    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('This email is already registered.')

    # custom validator - raise error if username already used
    def validate_name(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('This name is already registered.')


class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Length(5, 64), Email()], render_kw={"placeholder": "Email"})
    password = PasswordField('Password', validators=[DataRequired()], render_kw={"placeholder": "Password"})
    submit = SubmitField('Log In')


class ResetForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Length(5, 64), Email()],
                       render_kw={"placeholder": "Enter your email"})
    submit = SubmitField('Request Reset')


class NewPasswordForm(FlaskForm):
    password = PasswordField('Password', validators=[DataRequired(), EqualTo(fieldname='password_repeat',
                                                                             message='Passwords must match.')],
                             render_kw={"placeholder": "Your new password"})
    password_repeat = PasswordField('Confirm Password', validators=[DataRequired()],
                                    render_kw={"placeholder": "Repeat the password"})
    submit = SubmitField('Set new password')


class ChangePasswordForm(FlaskForm):
    old_password = PasswordField('Old Password', validators=[DataRequired()])
    password = PasswordField('New Password', validators=[DataRequired(), EqualTo(fieldname='password_repeat',
                                                                                 message='Passwords must match.')])
    password_repeat = PasswordField('Repeat New Password', validators=[DataRequired()])
    submit = SubmitField('Set new password')


### VIEWS FORMS ###
class UploadForm(FlaskForm):
    file = FileField('Upload Picture', validators=[DataRequired(), FileAllowed(['jpg', 'png', 'jpeg'],
                                                                               'File was not accepted. Please upload images only.')])
    description = TextAreaField('Description', validators=[DataRequired(), Length(1, 750)])
    private = BooleanField('Disable comments and likes')
    location = BooleanField('Share your current location')
    submit = SubmitField('Upload')


class SettingsForm(FlaskForm):
    description = TextAreaField('Description', validators=[DataRequired(), Length(1, 750)])
    file = FileField('New Profile Picture',
                     validators=[
                         FileAllowed(['jpg', 'png', 'jpeg'], 'File was not accepted. Please upload images only.')])
    not_recommend = BooleanField('Do not recommend profile')
    submit = SubmitField('Save Edits')


class DeleteForm(FlaskForm):
    confirmation = StringField('Confirmation', validators=[DataRequired(), Length(1, 200)])
    delete = SubmitField('Delete')

    # custom validator - user confirmation required
    def validate_confirmation(self, field):
        if field.data != f"delete {current_user.username}":
            raise ValidationError('If you want to delete this profile, please enter the confirmation message.')


class CommentForm(FlaskForm):
    text = TextAreaField('Your Comment', validators=[DataRequired(), Length(1, 750)])
    submit = SubmitField('Post')


class StoryForm(FlaskForm):
    file = FileField('Upload Picture', validators=[DataRequired(), FileAllowed(['jpg', 'png', 'jpeg'],
                                                                               'File was not accepted. Please upload images only.')])
    time_span = SelectField('Show for', validators=[DataRequired()], choices=[('12', '12 Hours'),
                                                                              ('24', '24 Hours'),
                                                                              ('48', '48 Hours'),
                                                                              ('72', '72 Hours')])
    submit = SubmitField('Upload')


class MessageForm(FlaskForm):
    text = StringField('Your Message', validators=[DataRequired(), Length(1, 3000)])
    submit = SubmitField('Send Message')


### SEARCH FORM ###
class SearchForm(FlaskForm):
    q = StringField('Search Users', validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        if 'formdata' not in kwargs:
            kwargs['formdata'] = request.args
        if 'meta' not in kwargs:
            kwargs['meta'] = {'csrf': False}
        super(SearchForm, self).__init__(*args, **kwargs)