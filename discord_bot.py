import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import json
import os
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# Bot Setup
intents = discord.Intents.default()
intents.message_content = False
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# MongoDB Connection
mongo_client = AsyncIOMotorClient(os.getenv('MONGO_URL', 'mongodb://localhost:27017'))
db = mongo_client['notruf_hamburg_bot']

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="🎫 Wähle ein Thema aus...",
        options=[
            discord.SelectOption(
                label="🔗 Roblox Verifizierung",
                description="Verifiziere deinen Roblox Account",
                value="roblox_verify",
                emoji="🔗"
            ),
            discord.SelectOption(
                label="💰 Geld einzahlen",
                description="Geld auf dein Konto einzahlen",
                value="bank_deposit",
                emoji="💰"
            ),
            discord.SelectOption(
                label="💸 Geld auszahlen",
                description="Geld von deinem Konto abheben",
                value="bank_withdraw",
                emoji="💸"
            )
        ]
    )
    async def ticket_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "roblox_verify":
            await self.handle_roblox_verify(interaction)
        elif select.values[0] == "bank_deposit":
            await self.handle_bank_deposit(interaction)
        elif select.values[0] == "bank_withdraw":
            await self.handle_bank_withdraw(interaction)

    async def handle_roblox_verify(self, interaction):
        modal = RobloxVerifyModal()
        await interaction.response.send_modal(modal)

    async def handle_bank_deposit(self, interaction):
        # Check if user is verified
        user_data = await db.users.find_one({"discord_id": str(interaction.user.id)})
        if not user_data or not user_data.get('verified'):
            embed = discord.Embed(
                title="❌ Nicht verifiziert",
                description="Du musst zuerst deinen Roblox Account verifizieren!",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        modal = BankDepositModal()
        await interaction.response.send_modal(modal)

    async def handle_bank_withdraw(self, interaction):
        # Check if user is verified
        user_data = await db.users.find_one({"discord_id": str(interaction.user.id)})
        if not user_data or not user_data.get('verified'):
            embed = discord.Embed(
                title="❌ Nicht verifiziert", 
                description="Du musst zuerst deinen Roblox Account verifizieren!",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        modal = BankWithdrawModal()
        await interaction.response.send_modal(modal)

class RobloxVerifyModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🔗 Roblox Verifizierung")

    username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Gib deinen Roblox Username ein...",
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Get Roblox user data
        roblox_data = await get_roblox_user_data(self.username.value)
        
        if not roblox_data:
            embed = discord.Embed(
                title="❌ Benutzer nicht gefunden",
                description=f"Der Roblox Benutzer `{self.username.value}` konnte nicht gefunden werden!",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Save to database
        user_data = {
            "discord_id": str(interaction.user.id),
            "discord_username": str(interaction.user),
            "roblox_username": roblox_data['name'],
            "roblox_id": roblox_data['id'],
            "verified": True,
            "verified_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "balance": 5000
        }
        
        await db.users.replace_one(
            {"discord_id": str(interaction.user.id)}, 
            user_data, 
            upsert=True
        )

        # Success embed
        embed = discord.Embed(
            title="✅ Erfolgreich verifiziert!",
            description=f"**Discord:** {interaction.user.mention}\n**Roblox:** {roblox_data['name']}",
            color=0x00ff00
        )
        embed.set_thumbnail(url=f"https://www.roblox.com/headshot-thumbnail/image?userId={roblox_data['id']}&width=420&height=420&format=png")
        embed.add_field(name="💰 Startguthaben", value="5.000€", inline=True)
        embed.add_field(name="📅 Verifiziert am", value=datetime.now().strftime("%d.%m.%Y %H:%M"), inline=True)
        
        await interaction.followup.send(embed=embed)

class BankDepositModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="💰 Geld einzahlen")

    amount = discord.ui.TextInput(
        label="Betrag (€)",
        placeholder="Wie viel möchtest du einzahlen?", 
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                raise ValueError("Betrag muss positiv sein")
        except ValueError:
            embed = discord.Embed(
                title="❌ Ungültiger Betrag",
                description="Bitte gib eine gültige Zahl ein!",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Update balance
        await db.users.update_one(
            {"discord_id": str(interaction.user.id)},
            {"$inc": {"balance": amount}}
        )

        # Log transaction
        transaction = {
            "discord_id": str(interaction.user.id),
            "type": "deposit",
            "amount": amount,
            "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        }
        await db.transactions.insert_one(transaction)

        embed = discord.Embed(
            title="✅ Einzahlung erfolgreich",
            description=f"**{amount:,}€** wurden erfolgreich eingezahlt!",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class BankWithdrawModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="💸 Geld abheben")

    amount = discord.ui.TextInput(
        label="Betrag (€)",
        placeholder="Wie viel möchtest du abheben?",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            if amount <= 0:
                raise ValueError("Betrag muss positiv sein")
        except ValueError:
            embed = discord.Embed(
                title="❌ Ungültiger Betrag",
                description="Bitte gib eine gültige Zahl ein!",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check balance
        user_data = await db.users.find_one({"discord_id": str(interaction.user.id)})
        if user_data['balance'] < amount:
            embed = discord.Embed(
                title="❌ Nicht genug Guthaben",
                description=f"Du hast nur **{user_data['balance']:,}€** auf deinem Konto!",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Update balance
        await db.users.update_one(
            {"discord_id": str(interaction.user.id)},
            {"$inc": {"balance": -amount}}
        )

        # Log transaction
        transaction = {
            "discord_id": str(interaction.user.id),
            "type": "withdraw",
            "amount": amount,
            "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        }
        await db.transactions.insert_one(transaction)

        embed = discord.Embed(
            title="✅ Auszahlung erfolgreich",
            description=f"**{amount:,}€** wurden erfolgreich abgehoben!",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def get_roblox_user_data(username):
    """Get Roblox user data from username"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://users.roblox.com/v1/usernames/users"
            data = {
                "usernames": [username],
                "excludeBannedUsers": True
            }
            
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get('data') and len(result['data']) > 0:
                        return result['data'][0]
                return None
    except Exception as e:
        print(f"Error getting Roblox data: {e}")
        return None

@bot.event
async def on_ready():
    print(f'{bot.user} ist online!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="setup", description="Setup das Ticket System")
async def setup_tickets(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Du brauchst Administrator-Rechte!", ephemeral=True)
        return

    embed = discord.Embed(
        title="🏢 Notruf Hamburg - Service Center",
        description="""**Willkommen beim Notruf Hamburg Bot!**

Hier kannst du folgende Services nutzen:

🔗 **Roblox Verifizierung**
Verbinde deinen Discord mit deinem Roblox Account

💰 **Bank Services**
• Geld einzahlen
• Geld abheben

**Wähle unten eine Option aus:**""",
        color=0x0099ff
    )
    embed.set_footer(text="Notruf Hamburg © 2025")

    view = TicketView()
    await interaction.response.send_message(embed=embed, view=view)

if __name__ == "__main__":
    bot.run(os.getenv('DISCORD_TOKEN'))
