from thesisound.audio_cli import register_audio_commands
from thesisound.cli import app
from thesisound.doctor_cli import register_doctor_command
from thesisound.search_cli import register_search_commands

register_audio_commands(app)
register_doctor_command(app)
register_search_commands(app)
