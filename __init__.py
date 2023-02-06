import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Tuple

import discord
from discord import app_commands
from discord.ext import tasks

import breadcord
from breadcord.module import ModuleCog


class DeleteMessageButton(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.should_delete_message = False

    @discord.ui.button(label='Delete message', style=discord.ButtonStyle.red, emoji="🚮")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.should_delete_message = True
        self.stop()


class BreadAssassin(ModuleCog):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.module_settings = self.bot.settings.BreadAssassin
        self.message_cache: defaultdict = defaultdict(dict)
        self.cache_cleanup.start()

    @staticmethod
    async def send_snipe_embed(
        interaction: discord.Interaction,
        old_message: discord.Message,
        new_message: discord.Message,
        changed_at: datetime,
    ) -> None:
        edited = new_message is not None

        embeds = [
            discord.Embed(title=f"{'Old message' if edited else 'Message'} content:", description=old_message.content)
        ]
        if edited:
            embeds.append(discord.Embed(title="New message content:", description=new_message.content))

        button = DeleteMessageButton()
        await interaction.response.send_message(
            f"Sniped message {'edit' if edited else 'deletion'} from <t:{int(time.mktime(changed_at.timetuple()))}:R>. "
            f"Message was sent by {old_message.author.mention}",
            embeds=embeds,
            view=button
        )
        await button.wait()
        if button.should_delete_message:
            await interaction.delete_original_response()


    async def send_snipe_response(
        self, interaction: discord.Interaction, *sniped_message_dict: Tuple[discord.Message, discord.Message, datetime]
    ):
        response_type: str = self.module_settings.snipe_response_type.value.lower()
        match response_type:
            case "embed":
                await self.send_snipe_embed(interaction, *sniped_message_dict)

    async def is_allowed_to_snipe(self, attempted_to_snipe: dict) -> bool:
        if attempted_to_snipe["new_message"] is None and not self.module_settings.allow_deletion_sniping.value:
            return False
        if attempted_to_snipe["new_message"] is not None and not self.module_settings.allow_edit_sniping.value:
            return False

        now = datetime.now()
        time_tolerance = timedelta(seconds=self.module_settings.max_age.value)
        return attempted_to_snipe["changed_at"] + time_tolerance >= now

    @app_commands.command()
    async def snipe(self, interaction: discord.Interaction):
        try:
            sniped_message_dict: dict = self.message_cache[interaction.guild_id][interaction.channel_id]
            assert await self.is_allowed_to_snipe(sniped_message_dict)
        except (KeyError, AssertionError):
            return await interaction.response.send_message("There is no message to snipe.", ephemeral=True)
        # Lowers the chance of double sniping occurring
        del self.message_cache[interaction.guild_id][interaction.channel_id]

        await self.send_snipe_response(interaction, *sniped_message_dict.values())

    @ModuleCog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not self.module_settings.deletion_sniping.value:
            return
        self.message_cache[message.guild.id][message.channel.id] = {
            "old_message": message,
            "new_message": None,
            "changed_at": datetime.now(),
        }

    @ModuleCog.listener()
    async def on_message_edit(self, old_message: discord.Message, new_message: discord.Message):
        if not self.module_settings.edit_sniping.value:
            return
        self.message_cache[old_message.guild.id][old_message.channel.id] = {
            "old_message": old_message,
            "new_message": new_message,
            "changed_at": datetime.now(),
        }

    @tasks.loop(seconds=1.0)
    async def cache_cleanup(self) -> None:
        now = datetime.now()
        time_tolerance = timedelta(seconds=self.module_settings.max_age.value)
        for guild, channels in dict(self.message_cache).items():
            # Cast to a dict in order to avoid modifying the object we're iterating over
            # This instead creates a copy of the object before iterating
            for channel, channel_data in dict(channels).items():
                if channel_data["changed_at"] + time_tolerance < now:
                    del self.message_cache[guild][channel]


async def setup(bot: breadcord.Bot):
    await bot.add_cog(BreadAssassin())
