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
    def __init__(self, *, sniped_user_id: int, sniper_user_id: int):
        super().__init__()
        self.accepted_users = (sniped_user_id, sniper_user_id)
        self.should_delete_message = False

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Delete this message (author only)", style=discord.ButtonStyle.red, emoji="🚮")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.accepted_users:
            await interaction.response.send_message('You are not allowed to perform this action!', ephemeral=True)
            return

        await interaction.response.defer()
        self.should_delete_message = True
        self.stop()


class BreadAssassin(ModuleCog):
    def __init__(self, module_id: str):
        super().__init__(module_id)
        self.message_cache: defaultdict = defaultdict(dict)
        self.cache_cleanup.start()

    @staticmethod
    async def send_snipe_embed(
        interaction: discord.Interaction,
        old_message: discord.Message,
        new_message: discord.Message | None,
        changed_at: datetime,
    ) -> None:
        edited = new_message is not None
        content = (
            f"Sniped message {'edit' if edited else 'deletion'} from <t:{int(time.mktime(changed_at.timetuple()))}:R>. "
            f"Message was sent by {old_message.author.mention} "
        )

        embeds = [
            discord.Embed(title=f"{'Old message' if edited else 'Message'} content:", description=old_message.content)
        ]
        if edited:
            embeds.append(discord.Embed(title="New message content:", description=new_message.content))
        if old_message.reference and (reply := old_message.reference.cached_message):
            content += f"in reply to {old_message.reference.cached_message.author.mention}"
            embeds.append(discord.Embed(title="Replying to:", description=reply.content))

        embeds.extend(old_message.embeds)
        button = DeleteMessageButton(sniped_user_id=old_message.author.id, sniper_user_id=interaction.user.id)
        await interaction.response.send_message(
            content,
            files=[await attachment.to_file() for attachment in old_message.attachments],
            embeds=embeds[:10],
            view=button,
        )
        await button.wait()
        if button.should_delete_message:
            await interaction.delete_original_response()

    async def send_snipe_webhook(
        self,
        interaction: discord.Interaction,
        old_message: discord.Message,
        new_message: discord.Message | None,
        changed_at: datetime,
    ) -> None:
        try:
            snipe_webhook: discord.Webhook | None = discord.utils.find(
                lambda w: w.name == "Snipe", await interaction.channel.webhooks()
            )
        except discord.Forbidden:
            self.logger.warn(
                f"Bot doesn't have permissions to manage webhooks in the "
                f"{interaction.channel.name} channel within the {interaction.guild.name} guild."
            )
            # Fallback to an embed
            return await self.send_snipe_embed(interaction, old_message, new_message, changed_at)

        if not snipe_webhook or not snipe_webhook.token:
            snipe_webhook = await interaction.channel.create_webhook(name="Snipe")

        embeds: list[discord.Embed] = []
        if old_message.reference and (reply := old_message.reference.cached_message):
            embeds.append(
                discord.Embed(
                    title="Replying to:",
                    description=reply.content,
                    timestamp=reply.created_at,
                    color=reply.author.color,
                ).set_author(name=reply.author.display_name, icon_url=reply.author.avatar.url)
            )
        embeds.extend(old_message.embeds)

        files = [
            await sticker.to_file() for sticker in old_message.stickers
        ].extend([
            await attachment.to_file() for attachment in old_message.attachments
        ])

        edited = new_message is not None
        button = DeleteMessageButton(sniped_user_id=old_message.author.id, sniper_user_id=interaction.user.id)
        sent_message = await snipe_webhook.send(
            allowed_mentions=discord.AllowedMentions.none(),
            avatar_url=old_message.author.avatar.url,
            content=old_message.content if len(old_message.content) < 2000 else f"{old_message.content[:2000-3]}...",
            embeds=old_message.embeds[:10],
            files=files[:10] if files is not None else [],
            username=f"{old_message.author.display_name} ({'edited' if edited else 'deleted'} message)",
            view=button,
            wait=True,
        )
        await interaction.response.send_message("Sniped message.", ephemeral=True)

        await button.wait()
        if button.should_delete_message:
            await sent_message.delete()

    async def send_snipe_response(
        self, interaction: discord.Interaction, *sniped_message_dict: Tuple[discord.Message, discord.Message, datetime]
    ):
        response_type: str = self.settings.snipe_response_type.value.lower()
        match response_type:
            case "embed":
                await self.send_snipe_embed(interaction, *sniped_message_dict)
            case "webhook":
                await self.send_snipe_webhook(interaction, *sniped_message_dict)

    async def is_allowed_to_snipe(self, attempted_to_snipe: dict) -> bool:
        new_message: discord.Message = attempted_to_snipe["new_message"]
        old_message: discord.Message = attempted_to_snipe["old_message"]

        if new_message is None and not self.settings.allow_deletion_sniping.value:
            return False
        if new_message is not None and not self.settings.allow_edit_sniping.value:
            return False
        if old_message.webhook_id:
            return False

        now = datetime.now()
        time_tolerance = timedelta(seconds=self.settings.max_age.value)
        return attempted_to_snipe["changed_at"] + time_tolerance >= now

    @app_commands.command(description='"Snipe" a message that was recently edited or deleted')
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
        if not self.settings.allow_deletion_sniping.value:
            return
        self.message_cache[message.guild.id][message.channel.id] = {
            "old_message": message,
            "new_message": None,
            "changed_at": datetime.now(),
        }

    @ModuleCog.listener()
    async def on_message_edit(self, old_message: discord.Message, new_message: discord.Message):
        if not self.settings.allow_edit_sniping.value:
            return
        self.message_cache[old_message.guild.id][old_message.channel.id] = {
            "old_message": old_message,
            "new_message": new_message,
            "changed_at": datetime.now(),
        }

    @tasks.loop(seconds=1.0)
    async def cache_cleanup(self) -> None:
        now = datetime.now()
        time_tolerance = timedelta(seconds=self.settings.max_age.value)
        for guild, channels in dict(self.message_cache).items():
            # Cast to a dict in order to avoid modifying the object we're iterating over
            # This instead creates a copy of the object before iterating
            for channel, channel_data in dict(channels).items():
                if channel_data["changed_at"] + time_tolerance < now:
                    del self.message_cache[guild][channel]


async def setup(bot: breadcord.Bot):
    await bot.add_cog(BreadAssassin("bread_assassin"))
