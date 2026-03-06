import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import aiohttp
import io
import os
from PIL import Image, ImageDraw, ImageFont

TOKEN = os.environ.get("TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

welcome_configs = {}

DEFAULT_CONFIG = {
    "canal_id": None,
    "mensagem": "Bem-vindo(a) ao servidor, {member}!",
    "imagem_url": None,
    "ativo": False,
}


def get_config(guild_id):
    if guild_id not in welcome_configs:
        welcome_configs[guild_id] = DEFAULT_CONFIG.copy()
    return welcome_configs[guild_id]


async def baixar_imagem(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def carregar_fonte(tamanho: int):
    caminhos = [
        "/data/data/com.termux/files/home/Oswald-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for caminho in caminhos:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except Exception:
            continue
    return ImageFont.load_default()


def desenhar_texto_com_sombra(draw, pos, texto, font, cor_texto=(255,255,255,255), sombra=(0,0,0,200), offset=3):
    x, y = pos
    for dx in [-offset, 0, offset]:
        for dy in [-offset, 0, offset]:
            if dx != 0 or dy != 0:
                draw.text((x+dx, y+dy), texto, font=font, fill=sombra)
    draw.text((x, y), texto, font=font, fill=cor_texto)


async def gerar_imagem_boas_vindas(member: discord.Member, bg_url: str) -> io.BytesIO:
    W, H = 900, 350

    bg = await baixar_imagem(bg_url)
    if bg:
        bg = bg.convert("RGBA").resize((W, H), Image.LANCZOS)
    else:
        bg = Image.new("RGBA", (W, H), (30, 60, 120, 255))

    draw = ImageDraw.Draw(bg)

    # ── Foto de perfil ──
    avatar_url = member.display_avatar.replace(size=256, format="png").url
    avatar_img = await baixar_imagem(avatar_url)

    avatar_size = 110
    avatar_y = 18

    if avatar_img:
        avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)

        avatar_circle = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
        avatar_circle.paste(avatar_img, (0, 0))
        avatar_circle.putalpha(mask)

        outer_size = avatar_size + 12
        outer_img = Image.new("RGBA", (outer_size, outer_size), (0, 0, 0, 0))
        ImageDraw.Draw(outer_img).ellipse((0, 0, outer_size, outer_size), fill=(80, 100, 255, 220))

        border_size = avatar_size + 6
        border_img = Image.new("RGBA", (border_size, border_size), (0, 0, 0, 0))
        ImageDraw.Draw(border_img).ellipse((0, 0, border_size, border_size), fill=(255, 255, 255, 255))
        border_img.paste(avatar_circle, (3, 3), avatar_circle)

        outer_img.paste(border_img, (3, 3), border_img)
        bg.paste(outer_img, (W // 2 - outer_size // 2, avatar_y), outer_img)

    font_bvindo = carregar_fonte(52)
    font_nome   = carregar_fonte(36)
    font_sub    = carregar_fonte(22)

    base_y = avatar_y + avatar_size + 14

    texto_bv = "BEM-VINDO(A)"
    bbox = draw.textbbox((0, 0), texto_bv, font=font_bvindo)
    tw = bbox[2] - bbox[0]
    desenhar_texto_com_sombra(draw, ((W - tw) // 2, base_y), texto_bv, font_bvindo)

    nome = member.display_name.upper()
    bbox2 = draw.textbbox((0, 0), nome, font=font_nome)
    tw2 = bbox2[2] - bbox2[0]
    nome_y = base_y + (bbox[3] - bbox[1]) + 4
    desenhar_texto_com_sombra(draw, ((W - tw2) // 2, nome_y), nome, font_nome,
                               cor_texto=(210, 230, 255, 255))

    linha_y = nome_y + (bbox2[3] - bbox2[1]) + 8
    draw.line([(W // 2 - 160, linha_y), (W // 2 + 160, linha_y)],
              fill=(255, 255, 255, 160), width=2)

    sub = "Sinta-se parte da familia!"
    bbox3 = draw.textbbox((0, 0), sub, font=font_sub)
    tw3 = bbox3[2] - bbox3[0]
    desenhar_texto_com_sombra(draw, ((W - tw3) // 2, linha_y + 8), sub, font_sub,
                               cor_texto=(200, 220, 255, 255))

    buffer = io.BytesIO()
    bg.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ─────────────────────────────────────────────
#   VIEW DE CONFIGURAÇÃO
# ─────────────────────────────────────────────

class ConfigBoasVindasView(discord.ui.View):
    def __init__(self, guild_id, interaction_user):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.interaction_user = interaction_user
        self.add_item(CanalSelect(guild_id, interaction_user))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("❌ Apenas quem abriu o painel pode usar!", ephemeral=True)
            return False
        return True

    def build_embed(self):
        cfg = get_config(self.guild_id)
        status = "✅ Ativo" if cfg["ativo"] else "❌ Inativo"
        canal = f"<#{cfg['canal_id']}>" if cfg["canal_id"] else "❌ Não definido"
        imagem = cfg["imagem_url"] or "❌ Não definida"

        embed = discord.Embed(title="⚙️ Configuração de Boas-Vindas", color=discord.Color.orange())
        embed.add_field(name="📌 Canal:", value=canal, inline=True)
        embed.add_field(name="🔔 Status:", value=status, inline=True)
        embed.add_field(name="💬 Mensagem:", value=f"`{cfg['mensagem']}`", inline=False)
        embed.add_field(name="🖼️ Imagem de fundo:", value=imagem, inline=False)
        embed.set_footer(text="Use {member} pra mencionar o usuário e {server} pro nome do servidor")
        return embed

    @discord.ui.button(label="💬 Mensagem", style=discord.ButtonStyle.secondary, row=1)
    async def editar_mensagem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MensagemModal(self.guild_id))

    @discord.ui.button(label="🖼️ Imagem de Fundo", style=discord.ButtonStyle.secondary, row=1)
    async def editar_imagem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ImagemModal(self.guild_id))

    @discord.ui.button(label="💾 Salvar", style=discord.ButtonStyle.success, row=2)
    async def salvar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="✅ **Configurações salvas!**", embed=self.build_embed(), view=self)

    @discord.ui.button(label="✅ Ativar", style=discord.ButtonStyle.primary, row=2)
    async def pronto(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_config(self.guild_id)
        if not cfg["canal_id"]:
            await interaction.response.send_message("❌ Selecione um canal primeiro!", ephemeral=True)
            return
        if not cfg["imagem_url"]:
            await interaction.response.send_message("❌ Defina uma imagem de fundo primeiro!", ephemeral=True)
            return
        cfg["ativo"] = True
        await interaction.response.edit_message(
            content="🟢 **Sistema de boas-vindas ATIVADO!**", embed=self.build_embed(), view=self)

    @discord.ui.button(label="🔴 Desativar", style=discord.ButtonStyle.danger, row=2)
    async def desativar(self, interaction: discord.Interaction, button: discord.ui.Button):
        get_config(self.guild_id)["ativo"] = False
        await interaction.response.edit_message(
            content="🔴 **Sistema desativado.**", embed=self.build_embed(), view=self)


class CanalSelect(discord.ui.ChannelSelect):
    def __init__(self, guild_id, interaction_user):
        super().__init__(
            placeholder="📌 Selecione o canal de boas-vindas...",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1, row=0
        )
        self.guild_id = guild_id
        self.interaction_user = interaction_user

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("❌ Apenas quem abriu o painel pode usar!", ephemeral=True)
            return
        canal = self.values[0]
        get_config(self.guild_id)["canal_id"] = canal.id
        view = ConfigBoasVindasView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content=f"📌 Canal definido: {canal.mention}",
            embed=view.build_embed(), view=view
        )


class MensagemModal(discord.ui.Modal, title="Mensagem de Boas-Vindas"):
    mensagem = discord.ui.TextInput(
        label="Mensagem",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: Bem-vindo(a) {member} ao {server}! 🎉",
        max_length=500
    )

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id
        self.mensagem.default = get_config(guild_id)["mensagem"]

    async def on_submit(self, interaction: discord.Interaction):
        get_config(self.guild_id)["mensagem"] = self.mensagem.value
        view = ConfigBoasVindasView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content="💬 Mensagem atualizada!", embed=view.build_embed(), view=view)


class ImagemModal(discord.ui.Modal, title="Imagem de Fundo"):
    url = discord.ui.TextInput(
        label="URL da Imagem de Fundo",
        placeholder="https://exemplo.com/imagem.png",
        max_length=500
    )

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id
        cfg = get_config(guild_id)
        if cfg["imagem_url"]:
            self.url.default = cfg["imagem_url"]

    async def on_submit(self, interaction: discord.Interaction):
        get_config(self.guild_id)["imagem_url"] = self.url.value.strip()
        view = ConfigBoasVindasView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content="🖼️ Imagem atualizada!", embed=view.build_embed(), view=view)


# ─────────────────────────────────────────────
#   EVENTO: MEMBRO ENTROU — CORRIGIDO
# ─────────────────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    try:
        cfg = get_config(member.guild.id)

        if not cfg["ativo"]:
            print(f"⚠️ Boas-vindas inativo para {member.guild.name}")
            return
        if not cfg["canal_id"]:
            print(f"⚠️ Canal não definido para {member.guild.name}")
            return
        if not cfg["imagem_url"]:
            print(f"⚠️ Imagem não definida para {member.guild.name}")
            return

        canal = member.guild.get_channel(cfg["canal_id"])
        if not canal:
            print(f"⚠️ Canal não encontrado: {cfg['canal_id']}")
            return

        mensagem = cfg["mensagem"]
        mensagem = mensagem.replace("{member}", member.mention)
        mensagem = mensagem.replace("{server}", member.guild.name)

        imagem_buffer = await gerar_imagem_boas_vindas(member, cfg["imagem_url"])
        arquivo = discord.File(fp=imagem_buffer, filename="boasvindas.png")
        await canal.send(content=mensagem, file=arquivo)
        print(f"✅ Boas-vindas enviado para {member.display_name} em {member.guild.name}")

    except Exception as e:
        print(f"❌ Erro no on_member_join: {e}")
        try:
            canal = member.guild.get_channel(cfg["canal_id"])
            if canal:
                mensagem = cfg["mensagem"]
                mensagem = mensagem.replace("{member}", member.mention)
                mensagem = mensagem.replace("{server}", member.guild.name)
                await canal.send(content=mensagem)
        except Exception:
            pass


# ─────────────────────────────────────────────
#   SLASH COMMAND
# ─────────────────────────────────────────────

@bot.tree.command(name="configurar_entrada", description="Configura o sistema de boas-vindas")
@app_commands.checks.has_permissions(administrator=True)
async def configurar_entrada(interaction: discord.Interaction):
    view = ConfigBoasVindasView(interaction.guild_id, interaction.user)
    await interaction.response.send_message(
        content="⚙️ **Painel de Boas-Vindas**\nConfigure abaixo:",
        embed=view.build_embed(),
        view=view,
        ephemeral=True
    )

@configurar_entrada.error
async def configurar_entrada_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ Você precisa ser **Administrador**!", ephemeral=True)


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comando(s) sincronizado(s)!")
    except Exception as e:
        print(f"❌ Erro ao sincronizar: {e}")


bot.run(TOKEN)
