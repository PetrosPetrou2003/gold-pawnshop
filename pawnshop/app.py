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

# Flask will automatically find templates/ and static/ folders
app = Flask(__name__)

# Configure logging
import logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# ============================================================================
# CONFIGURATION - Easy to modify
# ============================================================================

# API Configuration
API_KEY = "208b9e7f2e7d42e7bdf63684249fffe1"  # Your API key (for future use if upgrading)
EUR_USD_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"  # Free API for EUR/USD rate
SYMBOL = "XAUEUR"  # Gold price per troy ounce in EUR (target)

# Conversion constants
TROY_OUNCE_TO_GRAMS = 31.1035

# Karat purity factors
KARAT_PURITY = {
    24: 1.0,
    22: 0.9167,
    18: 0.75,
    14: 0.585,
    9: 0.375
}

# Business rules - Now configurable via admin panel
# Default values (can be changed in admin panel)
DEFAULT_CONFIG = {
    "discount_rate": 0.94,  # Fallback legacy value
    "interest_rate": 0.13,  # 13% interest per month
    "shop_name": "Gold Pawnshop",
    # Dynamic Pricing Settings
    "volatility_margins": {
        "low": 4.0,     # 4% margin (0.04) -> Buy at 96%
        "medium": 6.0,  # 6% margin (0.06) -> Buy at 94%
        "high": 8.0     # 8% margin (0.08) -> Buy at 92%
    },
    "volatility_thresholds": {
        "low_limit": 1.0,  # Volatility < 1% is LOW
        "high_limit": 3.0  # Volatility > 3% is HIGH
    }
}

# Configuration file paths
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
PRICE_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'price_history.json')

def load_config():
    """Load configuration from file, or use defaults if file doesn't exist."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                
                # Recursive update for nested dictionaries (like volatility_margins)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                    elif isinstance(value, dict) and isinstance(config[key], dict):
                        for sub_key, sub_val in value.items():
                            if sub_key not in config[key]:
                                config[key][sub_key] = sub_val
                                
                return config
        except Exception as e:
            app.logger.warning(f"Failed to load config: {e}, using defaults")
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        app.logger.error(f"Failed to save config: {e}")
        return False

# Load current configuration
config = load_config()

# ============================================================================
# DYNAMIC PRICING LOGIC
# ============================================================================

def update_price_history(price_eur):
    """Save the current price to history for volatility tracking."""
    history = []
    
    # Load existing history
    if os.path.exists(PRICE_HISTORY_FILE):
        try:
            with open(PRICE_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception as e:
            app.logger.warning(f"Failed to load price history: {e}")
            history = []
    
    # Append new price with timestamp
    history.append({
        "timestamp": time.time(),
        "price": price_eur,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    # Cleanup: Keep only last 14 days (approx 2 weeks)
    # Assuming update every load, limit to ~500 entries to be safe
    # Cleanup: Keep only last 14 days
    cutoff_time = time.time() - (14 * 24 * 3600)
    history = [h for h in history if h["timestamp"] > cutoff_time]
    
    # Provide a sort of limit if it gets too huge (e.g. 1000 entries)
    if len(history) > 1000:
        history = history[-1000:]
        
    # Save back
    try:
        with open(PRICE_HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except Exception as e:
        app.logger.error(f"Failed to save price history: {e}")

def calculate_volatility_state():
    """
    Calculate volatility over the last 14 days.
    Returns: (state, volatility_percent, details_dict)
    state: 'low', 'medium', 'high'
    """
    if not os.path.exists(PRICE_HISTORY_FILE):
        return 'medium', 0.0, {} # Default to medium if no data
        
    try:
        with open(PRICE_HISTORY_FILE, 'r') as f:
            history = json.load(f)
            
        # Filter for last 14 days
        cutoff_time = time.time() - (14 * 24 * 3600)
        recent_prices = [h['price'] for h in history if h['timestamp'] > cutoff_time]
        
        if len(recent_prices) < 2:
            return 'medium', 0.0, {"msg": "insufficient_data"}
            
        min_price = min(recent_prices)
        max_price = max(recent_prices)
        avg_price = sum(recent_prices) / len(recent_prices)
        
        # Volatility formula: (Max - Min) / Average
        volatility = ((max_price - min_price) / avg_price) * 100
        
        # Determine State
        thresholds = config.get('volatility_thresholds', DEFAULT_CONFIG['volatility_thresholds'])
        
        if volatility < thresholds['low_limit']:
            state = 'low'
        elif volatility > thresholds['high_limit']:
            state = 'high'
        else:
            state = 'medium'
            
        return state, volatility, {
            "min": min_price, 
            "max": max_price, 
            "avg": avg_price,
            "count": len(recent_prices)
        }
            
    except Exception as e:
        app.logger.error(f"Error calculating volatility: {e}")
        return 'medium', 0.0, {}

# ============================================================================
# FUNCTIONS (from gold_pawn_agent.py)
# ============================================================================

# Robust import for yfinance
try:
    import yfinance as yf
except (ImportError, TypeError, Exception) as e:
    logging.warning(f"Failed to import yfinance: {e}")
    yf = None

def fetch_gold_price():
    """
    Fetch current XAUEUR (gold price per troy ounce in EUR) using Yahoo Finance.
    """
    try:
        price_eur = None
        
        # Only try Yahoo Finance if module loaded successfully
        if yf:
            try:
                # Yahoo Finance Ticker for Gold in EUR
                # Strategy: Get Gold (USD) and USD/EUR rate from Yahoo
                gold_ticker = yf.Ticker("GC=F")
                gold_data = gold_ticker.history(period="1d")
                
                usd_eur_ticker = yf.Ticker("EUR=X") 
                forex_data = usd_eur_ticker.history(period="1d")
                
                if not gold_data.empty and not forex_data.empty:
                    # Get latest closing price
                    gold_usd = gold_data['Close'].iloc[-1]
                    eur_rate = forex_data['Close'].iloc[-1]
                    
                    price_eur = gold_usd * eur_rate
                    app.logger.info(f"YFinance Live: Gold ${gold_usd:.2f} | Rate {eur_rate:.4f} | Price €{price_eur:.2f}")
                    
                else:
                    app.logger.warning("YFinance returned empty data")
            except Exception as e:
                app.logger.warning(f"YFinance fetching error: {e}")

        # Fallback if Yahoo fails (Unlikely) or yf not available
        if price_eur is None:
            # STATIC fallback 
            price_eur = 3900.0
            app.logger.warning(f"Using static fallback gold price: €{price_eur:.2f}")

        # Update History
        # Only update history if the price looks "real" (not exactly 3900.0 unless that's real)
        # To avoid polluting history with fallback static data
        if abs(price_eur - 3900.0) > 0.01: 
             update_price_history(price_eur)
        
        return price_eur

    except Exception as e:
        app.logger.error(f"Critical error fetching gold price: {e}")
        return 3900.0


def get_current_margin_percentage():
    """Determine the current margin % based on volatility."""
    state, volatility, _ = calculate_volatility_state()
    margins = config.get('volatility_margins', DEFAULT_CONFIG['volatility_margins'])
    
    # Select margin based on state
    margin_percent = margins.get(state, margins['medium'])
    
    return margin_percent, state, volatility

def calculate_rates(xaueur_price):
    """Calculate buy/pawn price per gram for each karat using Dynamic Pricing."""
    
    # 1. Get Dynamic Margin
    margin_percent, volatility_state, volatility_val = get_current_margin_percentage()
    
    # Convert margin to discount rate (e.g., 6% margin -> 0.94 multiplier)
    discount_rate = 1.0 - (margin_percent / 100.0)
    
    app.logger.info(f"Dynamic Pricing Active: State={volatility_state}, Volatility={volatility_val:.2f}%, Margin={margin_percent}%")
    
    price_per_gram_eur = xaueur_price / TROY_OUNCE_TO_GRAMS
    
    rates = {}
    for karat, purity_factor in KARAT_PURITY.items():
        melt_value_per_gram = price_per_gram_eur * purity_factor
        raw_buy_price = melt_value_per_gram * discount_rate
        
        # NEW: Round to nearest 0.25 (Quarter Logic) to match user preference
        # 28.18 -> 28.25, 28.10 -> 28.00
        buy_pawn_price_per_gram = round(raw_buy_price * 4) / 4
        
        rates[karat] = {
            "melt_value": melt_value_per_gram,
            "buy_pawn_price": buy_pawn_price_per_gram
        }
    
    # Return extra metadata for UI display
    rates['_meta'] = {
        "volatility_state": volatility_state,
        "volatility_percent": volatility_val,
        "active_margin": margin_percent
    }
    
    return rates


def calculate_loan(karat, weight_in_grams, rates, interest_rate=None):
    """Calculate loan amount, interest, and total due."""
    if interest_rate is None:
        interest_rate = config.get('interest_rate', DEFAULT_CONFIG['interest_rate'])
    
    buy_pawn_price_per_gram = rates[karat]["buy_pawn_price"]
    melt_value_per_gram = rates[karat]["melt_value"]
    
    loan_amount = buy_pawn_price_per_gram * weight_in_grams
    interest_1_month = loan_amount * interest_rate
    total_due_after_1_month = loan_amount + interest_1_month
    total_melt_value = melt_value_per_gram * weight_in_grams
    
    due_date = datetime.now() + timedelta(days=30)
    
    return {
        "karat": karat,
        "weight_in_grams": float(weight_in_grams),
        "weight": float(weight_in_grams),
        "melt_value_per_gram": melt_value_per_gram,
        "total_melt_value": total_melt_value,
        "buy_pawn_price_per_gram": buy_pawn_price_per_gram,
        "loan_amount": loan_amount,
        "interest_1_month": interest_1_month,
        "total_due_after_1_month": total_due_after_1_month,
        "due_date": due_date.strftime("%Y-%m-%d")
    }

# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    """Main page - displays rate sheet and calculator."""
    try:
        # Fetch current gold price
        xaueur_price = fetch_gold_price()
        
        if xaueur_price is None:
            # Use fallback price if API fails
            try:
                eur_response = requests.get(EUR_USD_API_URL, timeout=5)
                eur_data = eur_response.json()
                eur_usd_rate = float(eur_data.get("rates", {}).get("EUR", 0.92))
                xaueur_price = 4200.0 * eur_usd_rate
            except Exception as e:
                app.logger.warning(f"Failed to fetch EUR/USD rate: {e}")
                xaueur_price = 3864.0  # Approximate fallback
        
        # Calculate rates for all karats
        rates = calculate_rates(xaueur_price)
        
        # Extract meta info if present
        meta_info = rates.pop('_meta', None)
        
        # Prepare karats list
        karats_list = sorted(KARAT_PURITY.keys(), reverse=True)
        
        return render_template('index.html', 
                             xaueur_price=xaueur_price,
                             rates=rates,
                             karats=karats_list,
                             meta_info=meta_info,
                             is_fallback=False if xaueur_price != 3900.0 else True)

    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()
        app.logger.error(f"Error in index route: {error_msg}")
        app.logger.error(error_trace)
        return f"Error: {error_msg}", 500


@app.route('/calculate', methods=['POST'])
def calculate():
    """Calculate loan details from form submission."""
    try:
        karat = int(request.form.get('karat'))
        weight = float(request.form.get('weight'))
        
        if karat not in KARAT_PURITY:
            return jsonify({"error": "Invalid karat. Must be one of: 9, 14, 18, 22, 24"}), 400
        
        if weight <= 0:
            return jsonify({"error": "Weight must be greater than 0"}), 400
        
        # Fetch current gold price
        xaueur_price = fetch_gold_price()
        if xaueur_price is None:
            # Fallback
            xaueur_price = 3864.0 # Roughly €4200 USD equivalent
        
        # Calculate rates
        rates = calculate_rates(xaueur_price)
        
        # Calculate loan
        loan_info = calculate_loan(karat, weight, rates)
        
        return jsonify(loan_info)
        
    except ValueError as e:
        return jsonify({"error": "Invalid input. Please enter valid numbers."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/rates', methods=['GET'])
def api_rates():
    """API endpoint to get current rates."""
    try:
        xaueur_price = fetch_gold_price()
        if xaueur_price is None:
             xaueur_price = 3864.0
        
        rates = calculate_rates(xaueur_price)
        meta_info = rates.pop('_meta', None)
        
        return jsonify({
            "xaueur_price": xaueur_price,
            "rates": rates,
            "meta": meta_info,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "message": "Gold Pawnshop Calculator is running"})


@app.route('/admin', methods=['GET'])
def admin_panel():
    """Admin panel to configure rates."""
    try:
        current_config = load_config()
        
        # Legacy support
        interest_percent = current_config.get('interest_rate', 0.13) * 100
        
        # New Dynamic Support
        margins = current_config.get('volatility_margins', DEFAULT_CONFIG['volatility_margins'])
        thresholds = current_config.get('volatility_thresholds', DEFAULT_CONFIG['volatility_thresholds'])
        
        # Calculate current volatility for display
        state, vol_percent, vol_details = calculate_volatility_state()
        
        return render_template('admin.html',
                             interest_percent=interest_percent,
                             shop_name=current_config.get('shop_name', 'Gold Pawnshop'),
                             margins=margins,
                             thresholds=thresholds,
                             current_volatility={
                                 "state": state,
                                 "percent": vol_percent,
                                 "details": vol_details
                             })
    except Exception as e:
        app.logger.error(f"Error loading admin panel: {e}")
        return f"Error loading admin panel: {e}", 500


@app.route('/admin/update', methods=['POST'])
def update_config():
    """Update configuration from admin panel."""
    try:
        # Get basic form data
        interest_percent = float(request.form.get('interest_percent', 13))
        shop_name = request.form.get('shop_name', 'Gold Pawnshop')
        
        # Get Volatility Margins
        margin_low = float(request.form.get('margin_low', 4.0))
        margin_medium = float(request.form.get('margin_medium', 6.0))
        margin_high = float(request.form.get('margin_high', 9.0))
        
        # Convert interest percentage to rate
        interest_rate = interest_percent / 100
        
        # Update config object
        current_config = load_config()
        current_config['interest_rate'] = interest_rate
        current_config['shop_name'] = shop_name
        
        # Update Margins
        current_config['volatility_margins'] = {
            "low": margin_low,
            "medium": margin_medium,
            "high": margin_high
        }
        
        # Save
        if save_config(current_config):
            # Reload global config
            global config
            config = load_config()
            
            return jsonify({
                "success": True,
                "message": "Dynamic Pricing Strategy updated!",
            })
        else:
            return jsonify({"error": "Failed to save configuration"}), 500
            
    except ValueError as e:
        return jsonify({"error": "Invalid input. Please enter valid numbers."}), 400
    except Exception as e:
        app.logger.error(f"Error updating config: {e}")
        return jsonify({"error": str(e)}), 500


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with detailed information."""
    error_trace = traceback.format_exc()
    app.logger.error(f"Internal Server Error: {error}")
    app.logger.error(error_trace)
    return f"""
    <html>
    <head><title>Internal Server Error</title></head>
    <body style="font-family: Arial; padding: 40px;">
        <h1>Internal Server Error</h1>
        <p>The server encountered an error. Check Render logs for details.</p>
        <pre style="background: #f5f5f5; padding: 20px;">{error_trace}</pre>
    </body>
    </html>
    """, 500


if __name__ == '__main__':
    # Set debug=False for production deployment
    # Change to debug=True only for local development
    import os
    DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=DEBUG_MODE, host='0.0.0.0', port=5001)
\n
