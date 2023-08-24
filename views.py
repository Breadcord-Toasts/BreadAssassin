import discord


class DeleteMessageButton(discord.ui.View):
    def __init__(self, *, sniped_user_id: int, sniper_user_id: int):
        super().__init__()
        self.accepted_users = (sniped_user_id, sniper_user_id)
        self.should_delete = False

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Delete this message (author only)", style=discord.ButtonStyle.red, emoji="🚮")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.accepted_users:
            await interaction.response.send_message('You are not allowed to perform this action!', ephemeral=True)
            return

        await interaction.response.defer()
        self.should_delete = True
        self.stop()