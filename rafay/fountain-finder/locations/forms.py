from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

USERNAME_ATTRS = {
    "autocapitalize": "none",
    "autocorrect": "off",
    "spellcheck": "false",
    "autocomplete": "username",
}


class LoginForm(AuthenticationForm):
    """Login form with phone-friendly input attributes (no auto-capitalising, right keyboards)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(USERNAME_ATTRS)
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})


class SignupForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(USERNAME_ATTRS)
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].label = "Confirm password"
