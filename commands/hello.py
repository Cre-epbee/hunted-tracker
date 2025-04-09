# commands/hello.py

import discord

async def run_hello(interaction: discord.Interaction):
    await interaction.response.send_message("👋 Hello from commands/hello.py!", ephemeral=True)
