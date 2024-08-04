import os
import telebot
import requests
from flask import Flask, request
from telebot import types
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

user_states = {}
user_url_queue = {}

class UserStates:
    AWAITING_URL = 1
    PROCESSING_SECTIONS = 2
    AWAITING_SECTION_URL = 3

def fetchData(soup):
    questionsList = []
    optionList = []
    answerList = []
    
    questionStatement = soup.find_all(class_='bix-td-qtxt table-responsive w-100')
    optionContainer = soup.find_all(class_='bix-tbl-options')
    
    for i in questionStatement:
        questionsList.append(i.text.strip())
    
    for container in optionContainer:
        options = []
        for j in container.find_all(class_='bix-td-option-val d-flex flex-row align-items-center'):
            option_text = j.text.strip()
            options.append(option_text)
        optionList.append(options)

    correct_answers_inputs = soup.find_all('input', class_='jq-hdnakq')
    for input_field in correct_answers_inputs:
        value = input_field['value']
        if value:
            answerList.append(f"{value}")
    
    return questionsList, optionList, answerList

def mainFunction(URL, bot, chat_id):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.3; Win 64 ; x64) Apple WeKit /537.36(KHTML , like Gecko) Chrome/80.0.3987.162 Safari/537.36'
    }
    
    questionsList = []
    optionList = []
    answerList = []
    
    webpage = requests.get(URL, headers=headers, verify=False).text
    print(f"Fetching: {URL}")
    bot.send_message(chat_id, f"*Generating quiz from this URL:* \n`{URL}`", parse_mode="Markdown")
    soup = BeautifulSoup(webpage, 'lxml')
    
    questions, options, answers = fetchData(soup)
    questionsList.extend(questions)
    optionList.extend(options)
    answerList.extend(answers)
    
    try:
        second_page_url = str(soup.find_all(class_='page-item')[3])
        slicing_index = int(second_page_url.find('href'))
        urlprefix = second_page_url[slicing_index:].split('"')[1].split('/')[-1][:-2]
        pages = int(soup.find(class_='breadcrumb-item active').text.strip().split()[-1])

        for i in range(2, pages+1):
            if i <= 9:
                new_url = URL+f'{urlprefix}0{i}'
            else:
                new_url = URL+f'{urlprefix}{i}'
            webpage = requests.get(new_url, headers=headers, verify=False).text
            soup = BeautifulSoup(webpage, 'lxml')
            questions, options, answers = fetchData(soup)
            questionsList.extend(questions)
            optionList.extend(options)
            answerList.extend(answers)
    except:
        pass
    
    return questionsList, optionList, answerList

def send_quiz(bot, chat_id, question_number, question, options, correct_answer):
    option_labels = ['A', 'B', 'C', 'D']
    try:
        correct_option_index = option_labels.index(correct_answer)
    except:
        print("An error occurred")
        return

    try:
        truncated_question = question[:300]  # Truncate question to 300 characters
        bot.send_poll(
            chat_id,
            f"Q{question_number}: {truncated_question}",
            options,
            type='quiz',
            correct_option_id=correct_option_index,
            is_anonymous=False
        )
    except Exception as e:
        print(f"An exception occurred: {e}")

def scrapeFunction(url, bot, chat_id):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.3; Win 64 ; x64) Apple WeKit /537.36(KHTML , like Gecko) Chrome/80.0.3987.162 Safari/537.36'
    }
    
    webpage = requests.get(url, headers=headers, verify=False).text
    soup = BeautifulSoup(webpage, 'lxml')
    allsection = soup.find_all(class_='need-ul-filter')[0].find_all('li')
    sectionList = [url[:url.find('questions-and-answers')]+str(eachsection.text.strip()).lower().replace("'", '').replace('.', '').replace(' ', '-')+'/' for eachsection in allsection]
    
    user_url_queue[chat_id] = sectionList
    process_next_url(chat_id)

def process_next_url(chat_id):
    if user_url_queue[chat_id]:
        URL = user_url_queue[chat_id][0]
        markup = types.InlineKeyboardMarkup(row_width=2)
        yes_button = types.InlineKeyboardButton("Yes", callback_data=f"yes_{URL}")
        no_button = types.InlineKeyboardButton("No", callback_data=f"no_{URL}")
        cancel_button = types.InlineKeyboardButton("🛑 Stop Quiz Now", callback_data=f"cancel_{URL}")
        markup.add(yes_button, no_button, cancel_button)
        bot.send_message(chat_id, f"*Do you want to proceed with this URL?*\n`{URL}`", parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, "All sections have been processed. You can send a new URL if you'd like to scrape another page.")
        user_states[chat_id] = UserStates.AWAITING_URL

@bot.callback_query_handler(func=lambda call: call.data.startswith('yes_') or call.data.startswith('no_') or call.data.startswith('cancel_'))
def handle_url_confirmation(call):
    action, URL = call.data.split('_', 1)
    chat_id = call.message.chat.id
    
    if action == "yes":
        questionsList, optionList, answerList = mainFunction(URL, bot, chat_id)
        for index, (question, options) in enumerate(zip(questionsList, optionList), 1):
            send_quiz(bot, chat_id, index, question, options, answerList[index-1])
        bot.send_message(chat_id, f"Processed URL: {URL}", parse_mode="Markdown")
    elif action == "no":
        bot.send_message(chat_id, f"Skipped URL: {URL}", parse_mode="Markdown")
    elif action == "cancel":
        bot.send_message(chat_id, f"Cancelled the quiz successfully", parse_mode="Markdown")
        return

    bot.delete_message(chat_id, call.message.message_id)
    
    # Remove the processed URL from the queue
    user_url_queue[chat_id].pop(0)
    
    # Process the next URL
    process_next_url(chat_id)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot_description = ("This bot can scrape the Indiabix website's sections such as Verbal Ability and Aptitude "
                       "and send back the questions as quizzes. Now, you can practice more efficiently.")

    welcome_text = f"Hey *{message.chat.first_name}*, welcome to *Indiabix Scrapper Bot*.\n\n{bot_description}"
    markup = types.InlineKeyboardMarkup(row_width=2)
    help_button = types.InlineKeyboardButton("Help", callback_data="help")
    sendurl_button = types.InlineKeyboardButton("Send URL", callback_data="sendurl")
    demo_button = types.InlineKeyboardButton("Demo", callback_data="demo")
    markup.add(help_button, sendurl_button, demo_button)
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")
    print(f"Sent welcome to {message.chat.first_name}")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "help":
        help_menu(call.message)
    elif call.data == "sendurl":
        request_url(call.message)
    elif call.data == "demo":
        send_demo(call.message)

@bot.message_handler(commands=['demo'])
def send_demo(message):
    demo_text = (
        "1. Click on the *Send URL* button\n"
        "2. Provide the URL of the Indiabix website section you're interested in.\n\n"
        "*Proper Format* ✅:\n"
        "`https://www.indiabix.com/aptitude/questions-and-answers/`\n"
        "\n`https://www.indiabix.com/data-interpretation/questions-and-answers/`\n"
        "\n`https://www.indiabix.com/verbal-ability/questions-and-answers/`\n"
        "\n`https://www.indiabix.com/logical-reasoning/questions-and-answers/`\n"
        "\n*Wrong Format* ❌:\n"
        "`https://www.indiabix.com/logical-reasoning/number-series/`\n"
        "\n`https://www.indiabix.com/placement-papers/companies/`\n"
        "\n`https://www.indiabix.com/online-test/aptitude-test/`\n"
        "\n`https://www.indiabix.com/puzzles/sudoku/`"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    sendurl_button = types.InlineKeyboardButton("Send URL", callback_data="sendurl")
    markup.add(sendurl_button)
    bot.send_message(chat_id=message.chat.id, text=demo_text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['sendurl'])
def request_url(message):
    bot.reply_to(message, "Please send the URL to process.")
    user_states[message.chat.id] = UserStates.AWAITING_URL

@bot.message_handler(func=lambda msg: user_states.get(msg.chat.id) == UserStates.AWAITING_URL and 'http' in msg.text)
def process_url(message):
    url = message.text
    bot.send_message(message.chat.id, 'Please wait, your quiz questions are being processed...')
    user_states[message.chat.id] = UserStates.PROCESSING_SECTIONS
    scrapeFunction(url, bot, message.chat.id)

@bot.message_handler(commands=['help'])
def help_menu(message):
    help_text = ("/start - Show the welcome message\n"
                 "/demo - How the bot works\n"
                 "/sendurl - Send the URL to Scrape\n"
                 "/sectionurl - Send a specific section URL to scrape\n"
                 "/help - Show this help menu")
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['sectionurl'])
def request_section_url(message):
    bot.reply_to(message, "Please send the specific section URL to process (e.g., https://www.indiabix.com/verbal-ability/antonyms/).")
    user_states[message.chat.id] = UserStates.AWAITING_SECTION_URL

@bot.message_handler(func=lambda msg: user_states.get(msg.chat.id) == UserStates.AWAITING_SECTION_URL and 'http' in msg.text)
def process_section_url(message):
    url = message.text
    bot.send_message(message.chat.id, 'Please wait, your quiz questions are being processed...')
    questionsList, optionList, answerList = mainFunction(url, bot, message.chat.id)
    for index, (question, options) in enumerate(zip(questionsList, optionList), 1):
        send_quiz(bot, message.chat.id, index, question, options, answerList[index-1])
    bot.send_message(message.chat.id, f"Processed URL: {url}", parse_mode="Markdown")
    user_states[message.chat.id] = UserStates.AWAITING_URL

@bot.message_handler(func=lambda msg: True)
def default_reply(message):
    bot.reply_to(message, f"Sorry {message.chat.first_name}, the bot can only work with Indiabix URLs.")
    print(f"Replied to message from {message.chat.first_name}")

# Define a route for the Flask app
@app.route('/')
def hello_world():
    return 'Hello, World!'

if __name__ == '__main__':
    # Start the Flask app in a separate thread
    from threading import Thread
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=5000))
    flask_thread.start()
    
    # Start the bot
    print("Bot started and awaiting messages...")
    bot.infinity_polling()