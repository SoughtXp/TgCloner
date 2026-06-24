import asyncio
from telethon import functions
from telethon.tl.types import MessageReplyHeader, Updates, MessageMediaWebPage
from telethon.errors import FloodWaitError
from colorama import Fore, Style

from src.utils import check_cancel_prompt, list_and_choose_chat
from src.database import init_db, is_already_cloned, register_clone

async def run_cloner(client):
    print(f"{Fore.GREEN}Successfully connected to Telegram!")
    init_db()

    source = await list_and_choose_chat(client, "SELECT SOURCE CHANNEL (COPY FROM)")
    destination = await list_and_choose_chat(client, "SELECT DESTINATION CHANNEL (CLONE TO)")

    if source.id == destination.id:
        print(f"{Fore.RED}Error: Source and destination channels cannot be the same.")
        return

    print(f"\n{Fore.LIGHTBLACK_EX}💡 Tip: Press Ctrl + C at any time to pause or cancel the script.")

    is_forum = getattr(destination, 'forum', False)

    topic_map = {}
    if is_forum:
        # Scans destination to map existing topics by title, preventing duplicate creation on subsequent runs
        print(f"\n{Fore.YELLOW}[PHASE 1] Scanning destination existing topics...")
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
            print(f"{Fore.GREEN}Found {len(existing_topics)} existing topics in destination.")
        except Exception as e:
            print(f"{Fore.RED}Warning: Could not fetch existing destination topics: {e}")

        # Scan source chat service messages to extract and recreate topic definitions
        print(f"\n{Fore.YELLOW}[PHASE 1] Initializing global topic scanning...")
        try:
            async for message in client.iter_messages(source, reply_to=None):
                if message.action and hasattr(message.action, 'title'):
                    topic_title = str(message.action.title).strip()
                    
                    if not topic_title or topic_title.lower() == 'none':
                        continue
                        
                    source_topic_id = message.id
                    title_lower = topic_title.lower().strip()
                    
                    if title_lower in existing_topics:
                        dest_topic_id = existing_topics[title_lower]
                        print(f"{Fore.BLUE}[Topic Exists]{Fore.WHITE} Using existing topic '{topic_title}' (ID: {dest_topic_id})")
                        topic_map[source_topic_id] = (dest_topic_id, topic_title)
                    else:
                        print(f"{Fore.BLUE}[Topic Found]{Fore.WHITE} Creating mapped topic '{topic_title}'...")
                        try:
                            result = await client(functions.messages.CreateForumTopicRequest(
                                peer=destination,
                                title=topic_title
                            ))
                            
                            dest_topic_id = None
                            if isinstance(result, Updates) and result.updates:
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
                            print(f"{Fore.RED}Error creating topic '{topic_title}': {e}")
        except (KeyboardInterrupt, asyncio.CancelledError):
            await check_cancel_prompt()

        try:
            async for msg in client.iter_messages(source, limit=400):
                if msg.reply_to and isinstance(msg.reply_to, MessageReplyHeader):
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
                                if isinstance(result, Updates) and result.updates:
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
        except (KeyboardInterrupt, asyncio.CancelledError):
            await check_cancel_prompt()

        print(f"\n{Fore.GREEN}✓ PHASE 1 COMPLETE! Total of {len(topic_map)} topics successfully mapped.")
    else:
        print(f"\n{Fore.GREEN}Destination is a regular channel/group. Skipping topic mapping phase.")

    print(f"{Fore.YELLOW}[PHASE 2] Starting media, message and file injection processing...{Style.RESET_ALL}\n")

    import os
    import json
    import re
    filters = {
        "blocked_words": "",
        "skip_links": False,
        "clone_text": True,
        "clone_media": True
    }
    if os.path.exists("filters.json"):
        try:
            with open("filters.json", "r", encoding="utf-8") as f:
                filters = json.load(f)
            print(f"{Fore.LIGHTBLACK_EX}💡 Active filters loaded from filters.json:")
            print(f"   Blocked words: '{filters.get('blocked_words')}'")
            print(f"   Skip links: {filters.get('skip_links')}")
            print(f"   Clone text: {filters.get('clone_text')}")
            print(f"   Clone media: {filters.get('clone_media')}\n")
        except:
            pass

    import sqlite3
    try:
        conn = sqlite3.connect("cloned_messages.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cloned_messages WHERE source_chat_id = ? AND dest_chat_id = ?", (int(source.id), int(destination.id)))
        counter = cursor.fetchone()[0]
        conn.close()
    except:
        counter = 0
    
    try:
        async for msg in client.iter_messages(source, reverse=True):
            text = msg.text or ""
            if not msg.media and not filters.get("clone_text", True):
                continue
            if msg.media and not filters.get("clone_media", True):
                continue
            if filters.get("skip_links", False):
                if re.search(r"https?://\S+|www\.\S+|t\.me/\S+", text, re.IGNORECASE):
                    print(f"{Fore.YELLOW}[Filter] Skipping message {msg.id}: contains links.")
                    continue
            blocked_str = filters.get("blocked_words", "")
            if blocked_str:
                words = [w.strip().lower() for w in blocked_str.split(",") if w.strip()]
                has_blocked = False
                for w in words:
                    if w in text.lower():
                        print(f"{Fore.YELLOW}[Filter] Skipping message {msg.id}: contains blocked word '{w}'.")
                        has_blocked = True
                        break
                if has_blocked:
                    continue

            if is_already_cloned(source.id, destination.id, msg.id):
                continue

            dest_topic_id = None
            topic_name = "Main Chat"
            if is_forum:
                source_topic_id = None
                if msg.reply_to and isinstance(msg.reply_to, MessageReplyHeader):
                    source_topic_id = msg.reply_to.reply_to_top_id or msg.reply_to.reply_to_msg_id
                
                if source_topic_id in topic_map:
                    dest_topic_id, topic_name = topic_map[source_topic_id]

            # Exclude WebPage previews from send_file since they represent link meta-data rather than physical file attachments
            has_real_media = msg.media and not isinstance(msg.media, MessageMediaWebPage)
            content_preview = "Text Message"
            if has_real_media:
                content_preview = type(msg.media).__name__.replace("MessageMedia", "")
                if msg.text:
                    content_preview += f" ({msg.text[:25].strip()}...)"
            elif msg.text:
                content_preview = f"\"{msg.text[:30].strip()}...\""

            original_text = msg.text if msg.text else ""
            
            while True:
                try:
                    print(f"{Fore.CYAN}[Copying]{Fore.WHITE} Sending to [{Fore.MAGENTA}{topic_name}{Fore.WHITE}] -> {Fore.YELLOW}{content_preview}")
                    
                    sent_msg = None
                    if has_real_media:
                        sent_msg = await client.send_file(destination, msg.media, caption=original_text, reply_to=dest_topic_id)
                    elif msg.text:
                        sent_msg = await client.send_message(destination, original_text, reply_to=dest_topic_id)
                    
                    if sent_msg:
                        register_clone(source.id, destination.id, msg.id, sent_msg.id)
                    
                    counter += 1
                    print(f"{Fore.GREEN}✓ Progress: {counter} items cloned successfully.\n")
                    await asyncio.sleep(1.5)
                    break
                    
                except FloodWaitError as e:
                    # Dynamically adjust to Telegram API rate limiting restrictions
                    print(f"{Fore.RED}Rate limit hit! Sleeping for {e.seconds}s...")
                    await asyncio.sleep(e.seconds)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    await check_cancel_prompt()
                except Exception as e:
                    print(f"{Fore.RED}Skipping broken item on message {msg.id}: {e}\n")
                    break
    except (KeyboardInterrupt, asyncio.CancelledError):
        await check_cancel_prompt()

    print(f"\n{Fore.GREEN}{Style.BRIGHT}🎉 SUCCESS! Clone completely updated. Total of {counter} items built.")
