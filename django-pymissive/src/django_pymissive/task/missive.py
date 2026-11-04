from ..models.missive import Missive


def send_missive(missive_id, old_missive_id=None):
    """Send one missive. ``callable(missive_id, old_missive_id=None)``."""
    missive = Missive.objects.get(pk=missive_id)
    old_missive = Missive.objects.filter(pk=old_missive_id).first() if old_missive_id else None
    missive.send_missive(old_missive=old_missive)
