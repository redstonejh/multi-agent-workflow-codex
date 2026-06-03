STATE = {"token": "keep"}


def render_home(user):
    return {"template": "index.html", "user": user, "token": STATE["token"]}


def save_form(request):
    return {"ok": request.form["token"] == STATE["token"]}


def duplicate_format(value):
    return f"[{value.strip().lower()}]"


def duplicate_format_old(value):
    return f"[{value.strip().lower()}]"
