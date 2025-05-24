import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import logging
from gtts import gTTS
import os
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
import json

TELEGRAM_TOKEN = "7048892283:AAGEQ3Q1Abi7_NlV9I7kYobgJjfsTYpThoU"
SPOONACULAR_API_KEY = "e7ad4f061df9416f841a758d91bb234b"
FAVORITES_FILE = "favorites.json"

logging.basicConfig(level=logging.INFO)

def load_favorites():
    if not os.path.exists(FAVORITES_FILE):
        return {}
    with open(FAVORITES_FILE, 'r') as f:
        return json.load(f)

def save_favorites(data):
    with open(FAVORITES_FILE, 'w') as f:
        json.dump(data, f)

def is_link_alive(url):
    try:
        response = requests.head(url, timeout=5)
        return response.status_code < 400
    except:
        return False

# ✅ This function was missing earlier
def get_recipes(ingredients, diet_filter=None):
    url = "https://api.spoonacular.com/recipes/findByIngredients"
    params = {
        "ingredients": ingredients,
        "number": 3,
        "apiKey": SPOONACULAR_API_KEY
    }
    if diet_filter and diet_filter != "none":
        params["diet"] = diet_filter
    res = requests.get(url, params=params).json()
    return [(r['id'], r['title'], r.get('image', '')) for r in res]

def get_recipe_details(recipe_id):
    instr_url = f"https://api.spoonacular.com/recipes/{recipe_id}/analyzedInstructions"
    info_url = f"https://api.spoonacular.com/recipes/{recipe_id}/information"
    ing_url = f"https://api.spoonacular.com/recipes/{recipe_id}/ingredientWidget.json"

    steps_data = requests.get(instr_url, params={"apiKey": SPOONACULAR_API_KEY}).json()
    info_data = requests.get(info_url, params={"apiKey": SPOONACULAR_API_KEY}).json()
    ing_data = requests.get(ing_url, params={"apiKey": SPOONACULAR_API_KEY}).json()

    steps = [step['step'] for step in steps_data[0]['steps']] if steps_data else []
    time = info_data.get('readyInMinutes', '?')
    video = info_data.get('spoonacularSourceUrl') or info_data.get('sourceUrl', '')
    if not is_link_alive(video):
        video = "(Video not available)"
    title = info_data.get('title', '')
    image = info_data.get('image', '')

    ingredients_list = []
    for ing in ing_data.get("ingredients", []):
        name = ing["name"].capitalize()
        qty = ing["amount"]["metric"]["value"]
        unit = ing["amount"]["metric"]["unit"]
        ingredients_list.append(f"- {name} — {qty} {unit}")

    return steps, time, video, title, image, ingredients_list
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 What’s in your fridge today?Just type a few ingredients (e.g. 'chicken, rice') and I'll show you some recipes.")

async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    favs = load_favorites()
    user_favs = favs.get(user_id, [])
    if not user_favs:
        await update.message.reply_text("❌ You have no favorites yet.")
        return
    keyboard = [[InlineKeyboardButton(f"🔄 {rid}", callback_data=f"fav_{rid}")] for rid in user_favs]
    await update.message.reply_text("⭐ Your Favorites:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ingredients'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🥗 Vegan", callback_data="filter_vegan"),
         InlineKeyboardButton("🕌 Halal", callback_data="filter_halal")],
        [InlineKeyboardButton("🍞 Gluten-Free", callback_data="filter_glutenfree"),
         InlineKeyboardButton("🚫 No Preference", callback_data="filter_none")]
    ]
    await update.message.reply_text("Do you have any dietary preferences?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("filter_"):
        filter_choice = query.data.replace("filter_", "")
        context.user_data['filter'] = filter_choice
        ingredients = context.user_data.get('ingredients', '')
        diet_map = {"vegan": "vegan", "glutenfree": "gluten free", "halal": None, "none": None}
        recipes = get_recipes(ingredients, diet_map.get(filter_choice))
        if not recipes:
            await query.message.reply_text("❌ No recipes found. Try other ingredients.")
            return
        keyboard = [[InlineKeyboardButton(f"🍽️ {title}", callback_data=f"select_{id}")] for id, title, img in recipes]
        context.user_data['recipes'] = {f"select_{id}": (id, title, img) for id, title, img in recipes}
        await query.message.reply_text("👉 Choose a recipe:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("select_"):
        recipe_id, title, image_url = context.user_data['recipes'][query.data]
        steps, time, video, title, image, ingredients_list = get_recipe_details(recipe_id)
        ingredients_text = "\n".join(ingredients_list)
        await query.message.reply_text(f"📦 You’ll need:\n{ingredients_text}")
        if not steps:
            await query.message.reply_text("❌ No steps available.")
            return
        context.user_data['steps'] = steps
        context.user_data['step_index'] = 0
        context.user_data['current_recipe'] = recipe_id
        caption = f"🍽️ {title}\n⏱ Time: {time} mins\n🎬 Video: {video}"
        keyboard = [
            [InlineKeyboardButton("🗣️ Voice Only", callback_data="mode_voice"),
             InlineKeyboardButton("📝 Text + Voice", callback_data="mode_text")],
            [InlineKeyboardButton("⭐ Add to Favorites", callback_data=f"favadd_{recipe_id}")]
        ]
        await query.message.reply_photo(photo=image_url, caption=caption)
        await query.message.reply_text("How would you like the instructions?", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("favadd_"):
        recipe_id = query.data.replace("favadd_", "")
        user_id = str(query.from_user.id)
        favs = load_favorites()
        if user_id not in favs:
            favs[user_id] = []
        if recipe_id not in favs[user_id]:
            favs[user_id].append(recipe_id)
            save_favorites(favs)
            await query.message.reply_text("⭐ Recipe added to favorites!")
        else:
            await query.message.reply_text("✅ Already in favorites.")
    elif query.data.startswith("fav_"):
        recipe_id = query.data.replace("fav_", "")
        steps, time, video, title, image, ingredients_list = get_recipe_details(recipe_id)
        context.user_data['steps'] = steps
        context.user_data['step_index'] = 0
        caption = f"🍽️ {title}\n⏱ Time: {time} mins\n🎬 Video: {video}"
        await query.message.reply_photo(photo=image_url, caption=caption)
        await send_step(query, context)
    elif query.data in ["mode_voice", "mode_text"]:
        context.user_data['mode'] = "voice_only" if query.data == "mode_voice" else "text_voice"
        await send_step(query, context)
    elif query.data in ["next", "prev", "repeat"]:
        if 'steps' not in context.user_data:
            await query.message.reply_text("⚠️ No active recipe. Send ingredients again.")
            return
        if query.data == "next":
            context.user_data['step_index'] += 1
        elif query.data == "prev":
            context.user_data['step_index'] = max(0, context.user_data['step_index'] - 1)
        await send_step(query, context)

async def send_step(update, context):
    i = context.user_data['step_index']
    steps = context.user_data['steps']
    mode = context.user_data.get('mode', 'text_voice')
    if i < len(steps):
        step_text = f"Step {i+1}: {steps[i]}"
        keyboard = [[InlineKeyboardButton("⬅️ Prev", callback_data="prev"),
                     InlineKeyboardButton("🔁 Repeat", callback_data="repeat"),
                     InlineKeyboardButton("➡️ Next", callback_data="next")]]
        if mode == "text_voice":
            await update.message.reply_text(step_text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("🔊 Sending voice instruction...", reply_markup=InlineKeyboardMarkup(keyboard))
        tts = gTTS(text=steps[i], lang='en')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
            tts.save(tmp.name)
            with open(tmp.name, 'rb') as audio_file:
                await update.message.reply_voice(voice=audio_file)
        os.remove(tmp.name)
    else:
        await update.message.reply_text("🎉 Recipe complete! Bon appétit! 🧑‍🍳")
        await context.bot.send_animation(chat_id=update.effective_chat.id, animation="https://media.giphy.com/media/l0MYu5zFfKQ2s3m5G/giphy.gif")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.voice.get_file()
    ogg_path = "/tmp/input.ogg"
    wav_path = "/tmp/input.wav"
    await file.download_to_drive(ogg_path)
    audio = AudioSegment.from_ogg(ogg_path)
    audio.export(wav_path, format="wav")
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio_data).lower()
        await update.message.reply_text(f"🎙️ You said: '{text}'")
        if "next" in text:
            context.user_data['step_index'] += 1
        elif "back" in text or "previous" in text:
            context.user_data['step_index'] = max(0, context.user_data['step_index'] - 1)
        await send_step(update, context)
    except Exception:
        await update.message.reply_text("⚠️ Could not understand your voice.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("favorites", show_favorites))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.run_polling()

if __name__ == "__main__":
    main()

