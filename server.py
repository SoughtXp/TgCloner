import os
import sys
import json
import queue
import asyncio
import threading
import sqlite3
import re
import traceback
from flask import Flask, request, jsonify, Response, render_template

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from telethon import TelegramClient, functions
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import Channel, MessageMediaWebPage

from src.config import CONFIG_FILE
from src.client import get_client as src_get_client
from src.database import init_db, is_already_cloned, register_clone

def get_client():
    return src_get_client(loop=loop)

base_dir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(base_dir, 'src', 'templates')
static_dir = os.path.join(base_dir, 'src', 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = 'tg_cloner_x_web_secret_key'

sse_listeners = []
sse_lock = threading.Lock()

loop = None
async_thread = None
phone_code_hash = None
current_phone = None
cloning_task = None
cloning_cancelled = False
cloning_active = False

def broadcast(event_type, data):
    event = {"type": event_type, "data": data}
    with sse_lock:
        for q in sse_listeners:
            q.put(event)

def start_async_loop():
    # Dedicated asyncio event loop running on a background thread to manage Telethon operations asynchronously
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_forever()

async_thread = threading.Thread(target=start_async_loop, daemon=True)
async_thread.start()

def run_async(coro):
    # Safely schedules and blocks on a coroutine execution in the background asyncio event loop thread
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

FILTERS_FILE = "filters.json"

def load_filters():
    if os.path.exists(FILTERS_FILE):
        try:
            with open(FILTERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {
        "blocked_words": "",
        "skip_links": False,
        "clone_text": True,
        "clone_media": True
    }

def save_filters(filters):
    try:
        with open(FILTERS_FILE, "w", encoding="utf-8") as f:
            json.dump(filters, f, ensure_ascii=False, indent=4)
    except:
        pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def status():
    config_exists = os.path.exists(CONFIG_FILE)
    api_id, api_hash = "", ""
    if config_exists:
        try:
            with open(CONFIG_FILE, "r") as f:
                lines = f.read().splitlines()
                if len(lines) >= 2:
                    api_id, api_hash = lines[0].strip(), lines[1].strip()
        except:
            pass

    connected = False
    is_auth = False
    if config_exists:
        try:
            client = get_client()
            if not client.is_connected():
                run_async(client.connect())
            is_auth = run_async(client.is_user_authorized())
            connected = True
        except Exception as e:
            broadcast("log", f"Connection error: {str(e)}")

    filters = load_filters()

    return jsonify({
        "connected": connected,
        "authorized": is_auth,
        "config_configured": config_exists,
        "api_id": api_id,
        "api_hash": api_hash,
        "phone": current_phone,
        "filters": filters
    })

@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.json
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    
    if not api_id or not api_hash:
        return jsonify({"success": False, "error": "Invalid API ID or API HASH"}), 400
        
    try:
        int(api_id)
    except ValueError:
        return jsonify({"success": False, "error": "API ID must be numeric"}), 400

    with open(CONFIG_FILE, "w") as f:
        f.write(f"{api_id}\n{api_hash}")

    import src.client
    if src.client._client is not None:
        try:
            run_async(src.client._client.disconnect())
        except Exception:
            pass
    src.client._client = None
    client = get_client()
    run_async(client.connect())
    
    broadcast("log", "API Credentials updated successfully.")
    return jsonify({"success": True})

@app.route('/api/auth/phone', methods=['POST'])
def auth_phone():
    global phone_code_hash, current_phone
    data = request.json
    phone = data.get('phone')
    if not phone:
        return jsonify({"success": False, "error": "Phone number required"}), 400

    client = get_client()
    try:
        if not client.is_connected():
            run_async(client.connect())
            
        result = run_async(client.send_code_request(phone))
        phone_code_hash = result.phone_code_hash
        current_phone = phone
        broadcast("log", f"Verification code sent to {phone}")
        return jsonify({"success": True})
    except Exception as e:
        broadcast("log", f"Error sending verification code: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/auth/code', methods=['POST'])
def auth_code():
    global phone_code_hash, current_phone
    data = request.json
    code = data.get('code')
    if not code or not current_phone or not phone_code_hash:
        return jsonify({"success": False, "error": "Invalid auth session state"}), 400

    client = get_client()
    try:
        run_async(client.sign_in(current_phone, code, phone_code_hash=phone_code_hash))
        broadcast("log", "Logged in successfully!")
        return jsonify({"success": True, "status": "authorized"})
    except SessionPasswordNeededError:
        broadcast("log", "Two-Step verification password needed.")
        return jsonify({"success": True, "status": "2fa_required"})
    except Exception as e:
        broadcast("log", f"Error entering code: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/auth/password', methods=['POST'])
def auth_password():
    data = request.json
    password = data.get('password')
    if not password:
        return jsonify({"success": False, "error": "Password required"}), 400

    client = get_client()
    try:
        run_async(client.sign_in(password=password))
        broadcast("log", "Logged in successfully with 2FA!")
        return jsonify({"success": True})
    except Exception as e:
        broadcast("log", f"Error checking password: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    global current_phone
    try:
        client = get_client()
        if client.is_connected():
            run_async(client.log_out())
    except:
        pass
        
    try:
        client = get_client()
        run_async(client.disconnect())
    except:
        pass
        
    for file in os.listdir('.'):
        if file.startswith('tgclonerx_session.'):
            try:
                os.remove(file)
            except:
                pass
                
    import src.client
    src.client._client = None
    current_phone = None
    
    broadcast("log", "Logged out successfully. Session file deleted.")
    return jsonify({"success": True})

@app.route('/api/chats', methods=['GET'])
def get_chats():
    client = get_client()
    try:
        if not client.is_connected():
            run_async(client.connect())
            
        if not run_async(client.is_user_authorized()):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
            
        chats = []
        dialogs = run_async(client.get_dialogs())
        for d in dialogs:
            if isinstance(d.entity, Channel):
                chats.append({
                    "id": d.entity.id,
                    "name": d.name,
                    "forum": getattr(d.entity, "forum", False)
                })
        return jsonify({"success": True, "chats": chats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

SESSION_FILE = "last_session.json"

@app.route('/api/session/save', methods=['POST'])
def save_session():
    data = request.json
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/session/load', methods=['GET'])
def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify({"success": True, **data})
        except Exception:
            pass
    return jsonify({"success": False})

@app.route('/api/events')
def sse_events():
    # Establishes an SSE event-stream to broadcast progress and logs to connected web browsers
    q = queue.Queue()
    with sse_lock:
        sse_listeners.append(q)
        
    def event_stream():
        yield "data: {\"type\": \"connected\"}\n\n"
        while True:
            try:
                # 20-second timeout keep-alive ping to prevent connection drops by clients/browsers
                event = q.get(timeout=20)
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield "data: {\"type\": \"ping\"}\n\n"
            except Exception:
                break
                
        with sse_lock:
            if q in sse_listeners:
                sse_listeners.remove(q)
                
    return Response(event_stream(), mimetype="text/event-stream")

async def run_cloner_process(source_id, dest_id, filters):
    # Core async copying loop orchestrated inside the background thread context
    global cloning_cancelled, cloning_active
    cloning_cancelled = False
    cloning_active = True
    
    client = get_client()
    
    broadcast("log", "Starting cloning process...")
    init_db()
    try:
        source = None
        destination = None
        # Resolves Telethon peer entity references by iterating user dialogs
        async for dialog in client.iter_dialogs():
            if isinstance(dialog.entity, Channel):
                if dialog.entity.id == int(source_id):
                    source = dialog.entity
                if dialog.entity.id == int(dest_id):
                    destination = dialog.entity
            if source and destination:
                break
        
        if not source or not destination:
            raise ValueError("Could not find source or destination channel in dialogs.")
    except Exception as e:
        traceback.print_exc()
        broadcast("log", f"Error resolving channels: {str(e)}")
        cloning_active = False
        broadcast("clone_status", {"status": "error", "error": str(e)})
        return

    is_forum = getattr(destination, 'forum', False)
    
    topic_map = {}
    if is_forum:
        broadcast("log", "[PHASE 1] Scanning destination existing topics...")
        existing_topics = {}
        try:
            result = await client(functions.messages.GetForumTopicsRequest(
                channel=destination,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=100
            ))
            if hasattr(result, 'topics') and result.topics:
                for t in result.topics:
                    if hasattr(t, 'title') and t.title:
                        existing_topics[t.title.lower().strip()] = t.id
            broadcast("log", f"Found {len(existing_topics)} existing topics in destination.")
        except Exception as e:
            broadcast("log", f"Warning: Could not fetch existing topics: {e}")
            
        broadcast("log", "[PHASE 1] Recreating source topics in destination...")
        try:
            async for message in client.iter_messages(source, reply_to=None):
                if cloning_cancelled:
                    broadcast("log", "Cloning process stopped by user.")
                    cloning_active = False
                    broadcast("clone_status", {"status": "stopped"})
                    return
                    
                if message.action and hasattr(message.action, 'title'):
                    topic_title = str(message.action.title).strip()
                    if not topic_title or topic_title.lower() == 'none':
                        continue
                        
                    source_topic_id = message.id
                    title_lower = topic_title.lower().strip()
                    
                    if title_lower in existing_topics:
                        dest_topic_id = existing_topics[title_lower]
                        broadcast("log", f"[Topic Exists] Using existing topic '{topic_title}' (ID: {dest_topic_id})")
                        topic_map[source_topic_id] = (dest_topic_id, topic_title)
                    else:
                        broadcast("log", f"[Topic Found] Recreating '{topic_title}' in target group...")
                        try:
                            result = await client(functions.messages.CreateForumTopicRequest(
                                peer=destination,
                                title=topic_title
                            ))
                            dest_topic_id = None
                            if hasattr(result, 'updates') and result.updates:
                                for u in result.updates:
                                    if hasattr(u, 'id'):
                                        dest_topic_id = u.id
                                        break
                            if not dest_topic_id:
                                dest_topic_id = result.updates[0].id

                            existing_topics[title_lower] = dest_topic_id
                            topic_map[source_topic_id] = (dest_topic_id, topic_title)
                            await asyncio.sleep(1.2)
                        except Exception as e:
                            broadcast("log", f"Error creating topic '{topic_title}': {str(e)}")
        except Exception as e:
            broadcast("log", f"Phase 1 error: {str(e)}")

        try:
            async for msg in client.iter_messages(source, limit=400):
                if cloning_cancelled:
                    return
                if msg.reply_to and hasattr(msg.reply_to, 'reply_to_top_id'):
                    top_id = msg.reply_to.reply_to_top_id or msg.reply_to.reply_to_msg_id
                    if top_id and top_id not in topic_map:
                        fallback_title = f"Room Thread {top_id}"
                        title_lower = fallback_title.lower().strip()
                        if title_lower in existing_topics:
                            dest_topic_id = existing_topics[title_lower]
                            topic_map[top_id] = (dest_topic_id, fallback_title)
                        else:
                            try:
                                result = await client(functions.messages.CreateForumTopicRequest(
                                    peer=destination,
                                    title=fallback_title
                                ))
                                dest_topic_id = None
                                if hasattr(result, 'updates') and result.updates:
                                    for u in result.updates:
                                        if hasattr(u, 'id'):
                                            dest_topic_id = u.id
                                            break
                                if not dest_topic_id:
                                    dest_topic_id = result.updates[0].id
                                    
                                existing_topics[title_lower] = dest_topic_id
                                topic_map[top_id] = (dest_topic_id, fallback_title)
                                await asyncio.sleep(1.2)
                            except:
                                pass
        except Exception:
            pass
            
        total_topics = len(topic_map)
        broadcast("log", f"✓ PHASE 1 COMPLETE! {total_topics} topics mapped.")
    else:
        broadcast("log", "Destination is a regular channel/group. Skipping topic creation phase.")

    broadcast("log", "[PHASE 2] Starting message copying...")

    try:
        conn = sqlite3.connect("cloned_messages.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cloned_messages WHERE source_chat_id = ? AND dest_chat_id = ?", (int(source_id), int(dest_id)))
        counter = cursor.fetchone()[0]
        conn.close()
    except Exception:
        counter = 0
    try:
        async for msg in client.iter_messages(source, reverse=True):
            if cloning_cancelled:
                broadcast("log", "Cloning process stopped by user.")
                cloning_active = False
                broadcast("clone_status", {"status": "stopped"})
                return

            text = msg.text or ""
            if not msg.media and not filters.get("clone_text", True):
                continue
            if msg.media and not filters.get("clone_media", True):
                continue
            if filters.get("skip_links", False):
                if re.search(r"https?://\S+|www\.\S+|t\.me/\S+", text, re.IGNORECASE):
                    broadcast("log", f"Skipping message {msg.id}: contains links.")
                    continue
            blocked_str = filters.get("blocked_words", "")
            if blocked_str:
                words = [w.strip().lower() for w in blocked_str.split(",") if w.strip()]
                has_blocked = False
                for w in words:
                    if w in text.lower():
                        broadcast("log", f"Skipping message {msg.id}: contains blocked word '{w}'.")
                        has_blocked = True
                        break
                if has_blocked:
                    continue

            # Idempotency check: Skip messages that were successfully cloned in previous executions
            if is_already_cloned(source_id, dest_id, msg.id):
                continue

            dest_topic_id = None
            topic_name = "Main Chat"
            if is_forum:
                source_topic_id = None
                if msg.reply_to:
                    source_topic_id = getattr(msg.reply_to, 'reply_to_top_id', None) or getattr(msg.reply_to, 'reply_to_msg_id', None)
                
                if source_topic_id in topic_map:
                    dest_topic_id, topic_name = topic_map[source_topic_id]

            # Link preview pages are returned as WebPage media but cannot be sent as files via the Telethon API
            has_real_media = msg.media and not isinstance(msg.media, MessageMediaWebPage)
            content_preview = "Text Message"
            if has_real_media:
                content_preview = type(msg.media).__name__.replace("MessageMedia", "")
                if msg.text:
                    content_preview += f" ({msg.text[:20]}...)"
            elif msg.text:
                content_preview = f"\"{msg.text[:20]}...\""

            original_text = msg.text if msg.text else ""
            
            while True:
                if cloning_cancelled:
                    return
                try:
                    broadcast("log", f"[Copying] Sending to [{topic_name}] -> {content_preview}")
                    sent_msg = None
                    if has_real_media:
                        sent_msg = await client.send_file(destination, msg.media, caption=original_text, reply_to=dest_topic_id)
                    elif msg.text:
                        sent_msg = await client.send_message(destination, original_text, reply_to=dest_topic_id)
                    
                    if sent_msg:
                        register_clone(source_id, dest_id, msg.id, sent_msg.id)
                    
                    counter += 1
                    broadcast("progress", {"count": counter, "current": content_preview, "topic": topic_name})
                    await asyncio.sleep(1.5)
                    break
                except FloodWaitError as e:
                    broadcast("log", f"Rate limit hit! Sleeping for {e.seconds}s...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    broadcast("log", f"Skipping broken item on message {msg.id}: {str(e)}")
                    break
    except Exception as e:
        broadcast("log", f"Phase 2 copying error: {str(e)}")
        cloning_active = False
        broadcast("clone_status", {"status": "error", "error": str(e)})
        return

    cloning_active = False
    broadcast("log", f"🎉 SUCCESS! Clone complete. Total of {counter} items cloned.")
    broadcast("clone_status", {"status": "completed", "total": counter})

@app.route('/api/clone/progress', methods=['GET'])
def clone_progress():
    source_id = request.args.get('source_id')
    dest_id = request.args.get('dest_id')
    if not source_id or not dest_id:
        return jsonify({"success": False, "error": "Missing chat IDs"}), 400
    try:
        conn = sqlite3.connect("cloned_messages.db")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM cloned_messages
            WHERE source_chat_id = ? AND dest_chat_id = ?
        """, (int(source_id), int(dest_id)))
        count = cursor.fetchone()[0]
        conn.close()
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/clone/start', methods=['POST'])
def clone_start():
    global cloning_task
    data = request.json
    source_id = data.get('source_id')
    dest_id = data.get('destination_id')

    if not source_id or not dest_id:
        return jsonify({"success": False, "error": "Source and Destination IDs required"}), 400

    filters = {
        "blocked_words": data.get('blocked_words', ''),
        "skip_links": bool(data.get('skip_links', False)),
        "clone_text": bool(data.get('clone_text', True)),
        "clone_media": bool(data.get('clone_media', True))
    }
    save_filters(filters)

    cloning_task = asyncio.run_coroutine_threadsafe(
        run_cloner_process(source_id, dest_id, filters), loop
    )
    return jsonify({"success": True})

@app.route('/api/clone/running', methods=['GET'])
def clone_running():
    return jsonify({"success": True, "running": cloning_active})

@app.route('/api/clone/stop', methods=['POST'])
def clone_stop():
    global cloning_cancelled, cloning_active
    cloning_cancelled = True
    cloning_active = False
    broadcast("log", "Stopping cloning process...")
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
