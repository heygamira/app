"""Push delivery.

``provider`` is the interface and its two implementations. The rules for
*whether* to notify somebody live in ``app.services.notifications``; this
package only knows how to hand a message to a device.
"""

from app.notifications.provider import (
    FakePushProvider,
    FirebasePushProvider,
    PushMessage,
    PushProvider,
    PushResult,
    classify,
    get_push_provider,
    set_push_provider,
)

__all__ = [
    "FakePushProvider",
    "FirebasePushProvider",
    "PushMessage",
    "PushProvider",
    "PushResult",
    "classify",
    "get_push_provider",
    "set_push_provider",
]
