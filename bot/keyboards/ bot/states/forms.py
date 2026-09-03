from aiogram.fsm.state import State, StatesGroup


class AddChannelStates(StatesGroup):
    waiting_for_forward = State()


class NewPostStates(StatesGroup):
    waiting_for_content = State()
    waiting_for_datetime = State()
    waiting_for_channels = State()
    confirming = State()


class SetTimezoneStates(StatesGroup):
    waiting_for_timezone = State()


class EditPostStates(StatesGroup):
    waiting_for_new_datetime = State()
