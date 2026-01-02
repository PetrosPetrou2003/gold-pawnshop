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
