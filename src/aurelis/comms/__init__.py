"""Structured communication between agents.

Messages are typed, sourced and scoped: a kind so the record stays queryable,
claims and evidence carried separately from the prose so assertions can be
checked against what they cite, and both a write-scope trigger and channel
membership deciding who may say anything at all.
"""

from aurelis.comms.channels import COMPANY_CHANNELS, Comms
from aurelis.comms.tables import Channel, ChannelKind, ChannelMember, Message, MessageKind, Priority

__all__ = [
    "COMPANY_CHANNELS",
    "Channel",
    "ChannelKind",
    "ChannelMember",
    "Comms",
    "Message",
    "MessageKind",
    "Priority",
]
