# ═══════════════════════════════════════════
#  МОЙ ИИ ЧАТ-БОТ — НЕЙРОСЕТЬ С НУЛЯ
#  Требует: pip install flask numpy
#  Запуск: python app.py
# ═══════════════════════════════════════════

import json
import os
import numpy as np
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# ═══════════════════════════════════════════
#  ТОКЕНИЗАТОР (Буквы → Числа)
# ═══════════════════════════════════════════
class Tokenizer:
    def __init__(self):
        self.char_to_idx = {}
        self.idx_to_char = {}
        self.vocab_size = 0

    def fit(self, text):
        chars = sorted(list(set(text)))
        self.char_to_idx = {ch: i for i, ch in enumerate(chars)}
        self.idx_to_char = {i: ch for ch, i in self.char_to_idx.items()}
        self.vocab_size = len(chars)
        return self

    def encode(self, text):
        return [self.char_to_idx[ch] for ch in text if ch in self.char_to_idx]

    def decode(self, indices):
        return ''.join([self.idx_to_char[i] for i in indices])

    def to_json(self):
        return {
            'char_to_idx': self.char_to_idx,
            'idx_to_char': {str(k): v for k, v in self.idx_to_char.items()},
            'vocab_size': self.vocab_size
        }

    @classmethod
    def from_json(cls, data):
        t = cls()
        t.char_to_idx = data['char_to_idx']
        t.idx_to_char = {int(k): v for k, v in data['idx_to_char'].items()}
        t.vocab_size = data['vocab_size']
        return t


# ═══════════════════════════════════════════
#  RNN НЕЙРОСЕТЬ С НУЛЯ
# ═══════════════════════════════════════════
class RNN:
    def __init__(self, vocab_size, hidden_size=128):
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.W_ih = np.random.randn(hidden_size, vocab_size) * 0.01
        self.W_hh = np.random.randn(hidden_size, hidden_size) * 0.01
        self.W_hy = np.random.randn(vocab_size, hidden_size) * 0.01
        self.b_h = np.zeros((hidden_size, 1))
        self.b_y = np.zeros((vocab_size, 1))
        self.cache = {}

    def _softmax(self, x):
        e_x = np.exp(x - np.max(x))
        return e_x / np.sum(e_x)

    def forward(self, inputs, h_prev=None):
        if h_prev is None:
            h_prev = np.zeros((self.hidden_size, 1))
        xs, hs, ys, ps = {}, {}, {}, {}
        hs[-1] = np.copy(h_prev)
        loss = 0
        for t in range(len(inputs)):
            xs[t] = np.zeros((self.vocab_size, 1))
            xs[t][inputs[t]] = 1
            hs[t] = np.tanh(self.W_ih @ xs[t] + self.W_hh @ hs[t-1] + self.b_h)
            ys[t] = self.W_hy @ hs[t] + self.b_y
            ps[t] = self._softmax(ys[t])
            if t < len(inputs) - 1:
                loss += -np.log(ps[t][inputs[t+1], 0] + 1e-8)
        self.cache = {'xs': xs, 'hs': hs, 'ys': ys, 'ps': ps}
        return loss, hs[len(inputs)-1]

    def backward(self, inputs):
        xs, hs, ps = self.cache['xs'], self.cache['hs'], self.cache['ps']
        dW_ih = np.zeros_like(self.W_ih)
        dW_hh = np.zeros_like(self.W_hh)
        dW_hy = np.zeros_like(self.W_hy)
        db_h = np.zeros_like(self.b_h)
        db_y = np.zeros_like(self.b_y)
        dh_next = np.zeros_like(hs[0])
        for t in reversed(range(len(inputs))):
            dy = np.copy(ps[t])
            if t < len(inputs) - 1:
                dy[inputs[t+1]] -= 1
            dW_hy += dy @ hs[t].T
            db_y += dy
            dh = self.W_hy.T @ dy + dh_next
            dh_raw = (1 - hs[t] ** 2) * dh
            dW_ih += dh_raw @ xs[t].T
            dW_hh += dh_raw @ hs[t-1].T
            db_h += dh_raw
            dh_next = self.W_hh.T @ dh_raw
        for d in [dW_ih, dW_hh, dW_hy, db_h, db_y]:
            np.clip(d, -5, 5, out=d)
        return dW_ih, dW_hh, dW_hy, db_h, db_y

    def update(self, dW_ih, dW_hh, dW_hy, db_h, db_y, lr):
        self.W_ih -= lr * dW_ih
        self.W_hh -= lr * dW_hh
        self.W_hy -= lr * dW_hy
        self.b_h -= lr * db_h
        self.b_y -= lr * db_y

    def sample(self, tokenizer, seed_text, n=200, temperature=1.0):
        h = np.zeros((self.hidden_size, 1))
        for ch in seed_text:
            x = np.zeros((self.vocab_size, 1))
            x[tokenizer.char_to_idx[ch]] = 1
            h = np.tanh(self.W_ih @ x + self.W_hh @ h + self.b_h)
        result = seed_text
        ix = tokenizer.char_to_idx[seed_text[-1]]
        for _ in range(n):
            x = np.zeros((self.vocab_size, 1))
            x[ix] = 1
            h = np.tanh(self.W_ih @ x + self.W_hh @ h + self.b_h)
            y = self.W_hy @ h + self.b_y
            y = y / temperature
            p = self._softmax(y).ravel()
            ix = np.random.choice(range(self.vocab_size), p=p)
            result += tokenizer.idx_to_char[ix]
        return result

    def to_json(self):
        return {
            'W_ih': self.W_ih.tolist(),
            'W_hh': self.W_hh.tolist(),
            'W_hy': self.W_hy.tolist(),
            'b_h': self.b_h.tolist(),
            'b_y': self.b_y.tolist(),
            'hidden_size': self.hidden_size,
            'vocab_size': self.vocab_size
        }

    @classmethod
    def from_json(cls, data):
        rnn = cls(data['vocab_size'], data['hidden_size'])
        rnn.W_ih = np.array(data['W_ih'])
        rnn.W_hh = np.array(data['W_hh'])
        rnn.W_hy = np.array(data['W_hy'])
        rnn.b_h = np.array(data['b_h'])
        rnn.b_y = np.array(data['b_y'])
        return rnn


# ═══════════════════════════════════════════
#  ОБУЧЕНИЕ + ЗАГРУЗКА МОДЕЛИ
# ═══════════════════════════════════════════
MODEL_PATH = 'model_weights.json'

TRAIN_DATA = """Привет! Как дела?
Отлично, спасибо! А у тебя?
У меня тоже всё хорошо.
Чем занимаешься?
Программирую нейросеть с нуля.
Круто! Без трансформеров?
Да, чистая математика на NumPy.
Это впечатляет. Какой размер скрытого слоя?
Сейчас 128, но можно и больше.
А какой loss?
CrossEntropy, классика.
Понятно. А backpropagation сам пишешь?
Конечно, градиенты вручную.
Молодец. Когда запускаешь?
Скоро на Render.
Отличный выбор для хостинга.
Спасибо! Надеюсь всё заработает.
Обязательно заработает. Удачи!
Спасибо, пока!
Пока, увидимся!"""

def train_model():
    tokenizer = Tokenizer().fit(TRAIN_DATA)
    rnn = RNN(tokenizer.vocab_size, hidden_size=128)
    SEQ_LENGTH = 20
    LR = 0.01
    EPOCHS = 5000
    smooth_loss = -np.log(1.0 / tokenizer.vocab_size) * SEQ_LENGTH
    p = 0
    text = TRAIN_DATA
    for epoch in range(EPOCHS):
        if p + SEQ_LENGTH + 1 >= len(text):
            hprev = np.zeros((128, 1))
            p = 0
        inputs = tokenizer.encode(text[p:p + SEQ_LENGTH])
        if len(inputs) < SEQ_LENGTH:
            p = 0
            continue
        loss, hprev = rnn.forward(inputs, hprev)
        grads = rnn.backward(inputs)
        rnn.update(*grads, LR)
        smooth_loss = smooth_loss * 0.999 + loss * 0.001
        if epoch % 1000 == 0:
            print(f"Epoch {epoch}, Loss: {smooth_loss:.4f}")
        p += SEQ_LENGTH
    model_data = {
        'tokenizer': tokenizer.to_json(),
        'rnn': rnn.to_json()
    }
    with open(MODEL_PATH, 'w', encoding='utf-8') as f:
        json.dump(model_data, f)
    print("✅ Модель обучена и сохранена!")
    return tokenizer, rnn

if not os.path.exists(MODEL_PATH):
    print("🚀 Начинаю обучение...")
    tokenizer, rnn = train_model()
else:
    print("📦 Загружаю модель...")
    with open(MODEL_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    tokenizer = Tokenizer.from_json(data['tokenizer'])
    rnn = RNN.from_json(data['rnn'])
    print("✅ Модель загружена!")


# ═══════════════════════════════════════════
#  HTML + CSS + JS
# ═══════════════════════════════════════════
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🧠 Мой ИИ Чат-Бот</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0e0;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}
.container{max-width:800px;width:100%}
h1{color:#00d4ff;text-align:center;font-size:2.8rem;margin-bottom:8px;text-shadow:0 0 20px rgba(0,212,255,0.3)}
.subtitle{text-align:center;color:#6b7280;margin-bottom:30px;font-size:1rem}
.chat-box{background:#111118;border:1px solid #1f1f2e;border-radius:16px;padding:20px;min-height:400px;max-height:500px;overflow-y:auto;margin-bottom:20px;box-shadow:0 0 30px rgba(0,212,255,0.05)}
.message{margin-bottom:16px;padding:14px 18px;border-radius:14px;max-width:85%;word-wrap:break-word;line-height:1.5;animation:fadeIn 0.3s ease}
.user{background:linear-gradient(135deg,#1a3a4a,#0d2a3a);margin-left:auto;border-bottom-right-radius:4px;color:#7dd3fc}
.bot{background:linear-gradient(135deg,#1a1a2e,#111118);margin-right:auto;border-bottom-left-radius:4px;color:#a5b4fc;border:1px solid #1f1f3a}
.typing{color:#6b7280;font-style:italic}
.input-area{display:flex;gap:12px}
input{flex:1;padding:14px 18px;border-radius:12px;border:1px solid #1f1f2e;background:#111118;color:#e0e0e0;font-size:1rem;outline:none;transition:0.2s}
input:focus{border-color:#00d4ff;box-shadow:0 0 10px rgba(0,212,255,0.1)}
button{padding:14px 28px;border-radius:12px;border:none;background:linear-gradient(135deg,#00d4ff,#0099cc);color:#0a0a0f;font-weight:bold;font-size:1rem;cursor:pointer;transition:0.2s}
button:hover{transform:translateY(-2px);box-shadow:0 5px 20px rgba(0,212,255,0.3)}
button:disabled{opacity:0.5;cursor:not-allowed;transform:none}
.info{margin-top:20px;text-align:center;color:#4b5563;font-size:0.85rem}
.info span{color:#00d4ff}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#1f1f2e;border-radius:3px}
</style>
</head>
<body>
<div class="container">
<h1>🧠 Мой ИИ Чат-Бот</h1>
<p class="subtitle">Нейросеть с нуля • RNN • NumPy • Без Transformers</p>
<div class="chat-box" id="chatBox">
<div class="message bot">Привет! Я нейросеть, обученная с нуля на чистой математике. Напиши что-нибудь!</div>
</div>
<div class="input-area">
<input type="text" id="userInput" placeholder="Напиши сообщение..." maxlength="100" autocomplete="off">
<button id="sendBtn" onclick="sendMessage()">Отправить</button>
</div>
<div class="info">
<span>Архитектура:</span> Vanilla RNN | <span>Скрытый слой:</span> 128 | <span>Токенизатор:</span> Char-level | <span>Обучение:</span> Backprop + CrossEntropy
</div>
</div>
<script>
const chatBox = document.getElementById('chatBox');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
userInput.addEventListener('keypress', (e) => { if(e.key === 'Enter') sendMessage(); });
function addMessage(text, isUser) {
    const div = document.createElement('div');
    div.className = 'message ' + (isUser ? 'user' : 'bot');
    div.textContent = text;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}
function addTyping() {
    const div = document.createElement('div');
    div.className = 'message bot typing';
    div.id = 'typing';
    div.textContent = 'Думаю...';
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}
function removeTyping() {
    const t = document.getElementById('typing');
    if(t) t.remove();
}
async function sendMessage() {
    const text = userInput.value.trim();
    if(!text) return;
    addMessage(text, true);
    userInput.value = '';
    sendBtn.disabled = true;
    addTyping();
    try {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text})
        });
        const data = await res.json();
        removeTyping();
        addMessage(data.reply, false);
    } catch(e) {
        removeTyping();
        addMessage('Ошибка соединения...', false);
    }
    sendBtn.disabled = false;
    userInput.focus();
}
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════
#  FLASK ROUTES
# ═══════════════════════════════════════════
@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_msg = data.get('message', '')
    if not user_msg:
        return jsonify({'reply': 'Напиши что-нибудь!'})
    seed = user_msg[-20:] if len(user_msg) > 20 else user_msg
    seed = seed + ' ' if not seed.endswith(' ') else seed
    reply = rnn.sample(tokenizer, seed, n=80, temperature=0.7)
    reply = reply[len(seed):].strip()
    for end_char in ['.', '!', '?', '\n']:
        idx = reply.find(end_char)
        if idx > 10:
            reply = reply[:idx+1]
            break
    if not reply:
        reply = "Интересно! Расскажи подробнее."
    return jsonify({'reply': reply})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
