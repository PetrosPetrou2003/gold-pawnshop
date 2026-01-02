#!/usr/bin/env python3
"""
Gold Pawnshop Web Application - Flask web interface for employees
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import requests
import traceback
import os
import json
import time
import math
import random
import yfinance as yf

app = Flask(__name__)

import logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# Conversion constants
TROY_OUNCE_TO_GRAMS = 31.1035

KARAT_PURITY = {
    24: 1.0, 22: 0.9167, 18: 0.75, 14: 0.585, 9: 0.375
}

DEFAULT_CONFIG = {
    "interest_rate": 0.13,
    "shop_name": "Gold Pawnshop",
    "volatility_margins": {"low": 4.0, "medium": 6.0, "high": 8.0},
    "volatility_thresholds": {"low_limit": 1.0, "high_limit": 3.0}
}

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
PRICE_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'price_history.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except:
        return False

config = load_config()

def update_price_history(price_eur):
    history = []
    if os.path.exists(PRICE_HISTORY_FILE):
        try:
            with open(PRICE_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except: pass
    
    history.append({"timestamp": time.time(), "price": price_eur})
    cutoff = time.time() - (14 * 24 * 3600)
    history = [h for h in history if h["timestamp"] > cutoff]
    try:
        with open(PRICE_HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except: pass

def calculate_volatility_state():
    if not os.path.exists(PRICE_HISTORY_FILE): return 'medium', 0.0, {}
    try:
        with open(PRICE_HISTORY_FILE, 'r') as f:
            history = json.load(f)
        cutoff = time.time() - (14 * 24 * 3600)
        prices = [h['price'] for h in history if h['timestamp'] > cutoff]
        if len(prices) < 2: return 'medium', 0.0, {}
        vol = ((max(prices) - min(prices)) / (sum(prices)/len(prices))) * 100
        thr = config.get('volatility_thresholds', DEFAULT_CONFIG['volatility_thresholds'])
        state = 'low' if vol < thr['low_limit'] else ('high' if vol > thr['high_limit'] else 'medium')
        return state, vol, {"count": len(prices)}
    except: return 'medium', 0.0, {}

def fetch_gold_price():
    try:
        gold = yf.Ticker("GC=F").history(period="1d")
        forex = yf.Ticker("EUR=X").history(period="1d")
        if not gold.empty and not forex.empty:
            price = gold['Close'].iloc[-1] * forex['Close'].iloc[-1]
            if abs(price - 3900.0) > 0.1: update_price_history(price)
            return price
        return 3900.0
    except: return 3900.0

def calculate_rates(price):
    state, vol, _ = calculate_volatility_state()
    margins = config.get('volatility_margins', DEFAULT_CONFIG['volatility_margins'])
    margin = margins.get(state, margins['medium'])
    disc = 1.0 - (margin / 100.0)
    base = price / TROY_OUNCE_TO_GRAMS
    rates = {k: {"melt_value": base * p, "buy_pawn_price": round(base * p * disc * 4) / 4} for k, p in KARAT_PURITY.items()}
    rates['_meta'] = {"state": state, "vol": vol, "margin": margin}
    return rates

@app.route('/')
def index():
    price = fetch_gold_price()
    rates = calculate_rates(price)
    meta = rates.pop('_meta')
    return render_template('index.html', xaueur_price=price, rates=rates, karats=sorted(KARAT_PURITY.keys(), reverse=True), meta_info=meta, is_fallback=(price == 3900.0))

@app.route('/calculate', methods=['POST'])
def calculate():
    try:
        k, w = int(request.form.get('karat')), float(request.form.get('weight'))
        price = fetch_gold_price()
        rate = calculate_rates(price)[k]["buy_pawn_price"]
        amt = rate * w
        intr = config.get('interest_rate', 0.13)
        return jsonify({"loan_amount": amt, "interest": amt * intr, "total": amt * (1 + intr)})
    except: return jsonify({"error": "invalid input"}), 400

@app.route('/admin')
def admin_panel():
    state, vol, det = calculate_volatility_state()
    return render_template('admin.html',
                         interest_percent=config.get('interest_rate', 0.13) * 100,
                         shop_name=config.get('shop_name', 'Gold Pawnshop'),
                         margins=config.get('volatility_margins', DEFAULT_CONFIG['volatility_margins']),
                         thresholds=config.get('volatility_thresholds', DEFAULT_CONFIG['volatility_thresholds']),
                         current_volatility={"state": state, "percent": vol, "details": det})

@app.route('/admin/update', methods=['POST'])
def update_config():
    try:
        config['interest_rate'] = float(request.form.get('interest_percent', 13)) / 100
        config['shop_name'] = request.form.get('shop_name', 'Gold Pawnshop')
        config['volatility_margins'] = {
            "low": float(request.form.get('margin_low', 4.0)),
            "medium": float(request.form.get('margin_medium', 6.0)),
            "high": float(request.form.get('margin_high', 8.0))
        }
        if save_config(config): return jsonify({"success": True})
        return jsonify({"error": "save failed"}), 500
    except: return jsonify({"error": "invalid"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)))
