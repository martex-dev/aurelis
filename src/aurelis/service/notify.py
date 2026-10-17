"""Tell the person at the machine, outside the record (M60).

The record already says when something broke, but nobody reads the record at
3am, and twice the company stopped thinking for days while every page that
said so sat unopened (the service was down 15-24 September; the subscription
login expired on 7 October and nobody noticed for eleven days). An alarm that
only exists where you have to go and look is not an alarm.

So a change of state (the company falls asleep, or wakes up) is also shown on
the desktop: a Windows toast notification, raised through PowerShell with no
extra module. Everywhere else, and whenever the toast cannot be shown, it is
printed to the service window. Nothing here can fail a wake.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

__all__ = ["Notifier", "desktop_notify"]

Notifier = Callable[[str, str], None]
"""``notify(title, body)``. Injected into the service so a test can collect
what would have been shown instead of showing it."""

_WINRT = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime] > $null"
)
_TOAST = (
    "$ErrorActionPreference = 'Stop'\n"
    + _WINRT
    + r"""
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $template.GetElementsByTagName('text')
$text.Item(0).AppendChild($template.CreateTextNode($env:AURELIS_TOAST_TITLE)) > $null
$text.Item(1).AppendChild($template.CreateTextNode($env:AURELIS_TOAST_BODY)) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""
)


def desktop_notify(title: str, body: str) -> None:
    """Show ``title`` and ``body`` on the desktop, or print them.

    The text travels in environment variables, never in the script, so
    nothing a vendor or a model wrote can become PowerShell.
    """
    print(f"[aurelis] {title}: {body}", file=sys.stderr, flush=True)
    if sys.platform != "win32":
        return
    env = dict(os.environ, AURELIS_TOAST_TITLE=title[:120], AURELIS_TOAST_BODY=body[:400])
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
            env=env,
            capture_output=True,
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return
