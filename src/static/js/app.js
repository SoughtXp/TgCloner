document.addEventListener('DOMContentLoaded', () => {
    const apiIdInput = document.getElementById('api-id');
    const apiHashInput = document.getElementById('api-hash');
    const configForm = document.getElementById('config-form');
    const apiStatusBadge = document.getElementById('api-status-badge');
    
    const authStatusBadge = document.getElementById('auth-status-badge');
    const phoneInput = document.getElementById('phone-number');
    const phoneForm = document.getElementById('phone-form');
    const verificationCodeInput = document.getElementById('verification-code');
    const codeForm = document.getElementById('code-form');
    const passwordInput = document.getElementById('2fa-password');
    const passwordForm = document.getElementById('password-form');
    const authorizedPhoneLabel = document.getElementById('authorized-phone-label');
    const btnLogout = document.getElementById('btn-logout');
    
    const authSteps = document.querySelectorAll('.auth-step');
    const backToPhoneBtns = document.querySelectorAll('.back-to-phone');
    
    const sourceChatSelect = document.getElementById('source-chat');
    const destChatSelect = document.getElementById('dest-chat');
    const btnRefreshChats = document.getElementById('btn-refresh-chats');
    
    const cloneStatusBadge = document.getElementById('clone-status-badge');
    const btnStartClone = document.getElementById('btn-start-clone');
    const btnStopClone = document.getElementById('btn-stop-clone');
    const progressCounter = document.getElementById('progress-counter');
    const currentActionLabel = document.getElementById('current-action');
    const progressBar = document.getElementById('progress-bar');
    const terminalLogs = document.getElementById('terminal-logs');

    const blockedWordsInput = document.getElementById('blocked-words');
    const skipLinksCheckbox = document.getElementById('skip-links');
    const cloneTextCheckbox = document.getElementById('clone-text');
    const cloneMediaCheckbox = document.getElementById('clone-media');

    let eventSource = null;
    let totalItemsCloned = 0;

    function showStep(stepId) {
        authSteps.forEach(step => {
            step.classList.remove('active');
        });
        const targetStep = document.getElementById(stepId);
        if (targetStep) {
            targetStep.classList.add('active');
        }
    }

    function addTerminalLine(text, type = 'system-line') {
        const line = document.createElement('div');
        line.className = `terminal-line ${type}`;
        
        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0];
        line.innerText = `[${timeStr}] ${text}`;
        
        terminalLogs.appendChild(line);
        terminalLogs.scrollTop = terminalLogs.scrollHeight;
    }

    async function checkStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            if (data.config_configured) {
                apiStatusBadge.innerText = 'API Saved';
                apiStatusBadge.className = 'status-badge connected';
                
                if (!apiIdInput.value && data.api_id) apiIdInput.value = data.api_id;
                if (!apiHashInput.value && data.api_hash) apiHashInput.value = data.api_hash;
            } else {
                apiStatusBadge.innerText = 'No API';
                apiStatusBadge.className = 'status-badge disconnected';
            }

            if (data.filters) {
                if (blockedWordsInput) blockedWordsInput.value = data.filters.blocked_words || '';
                if (skipLinksCheckbox) skipLinksCheckbox.checked = !!data.filters.skip_links;
                if (cloneTextCheckbox) cloneTextCheckbox.checked = !!data.filters.clone_text;
                if (cloneMediaCheckbox) cloneMediaCheckbox.checked = !!data.filters.clone_media;
            }

            if (data.authorized) {
                authStatusBadge.innerText = 'Connected';
                authStatusBadge.className = 'status-badge connected';
                authorizedPhoneLabel.innerText = data.phone ? `Connected as ${data.phone}` : 'Account Connected';
                showStep('step-authorized');
                
                btnRefreshChats.disabled = false;
                sourceChatSelect.disabled = false;
                destChatSelect.disabled = false;
                btnStartClone.disabled = false;
                loadChats();
            } else {
                authStatusBadge.innerText = 'Disconnected';
                authStatusBadge.className = 'status-badge disconnected';
                showStep('step-phone');
                
                btnRefreshChats.disabled = true;
                sourceChatSelect.disabled = true;
                destChatSelect.disabled = true;
                btnStartClone.disabled = true;
                
                sourceChatSelect.innerHTML = '<option value="">Waiting for connection...</option>';
                destChatSelect.innerHTML = '<option value="">Waiting for connection...</option>';
            }
        } catch (err) {
            console.error('Error fetching status:', err);
        }
    }

    async function loadChats() {
        sourceChatSelect.innerHTML = '<option value="">Fetching channels...</option>';
        destChatSelect.innerHTML = '<option value="">Fetching channels...</option>';
        
        try {
            const res = await fetch('/api/chats');
            const data = await res.json();
            
            if (data.success && data.chats.length > 0) {
                sourceChatSelect.innerHTML = '<option value="">Select Source...</option>';
                destChatSelect.innerHTML = '<option value="">Select Destination...</option>';
                
                data.chats.forEach(chat => {
                    const typeLabel = chat.forum ? 'Topics' : 'Normal';
                    const optionText = `${chat.name} (${typeLabel})`;
                    
                    const optSource = new Option(optionText, chat.id);
                    const optDest = new Option(optionText, chat.id);
                    
                    sourceChatSelect.add(optSource);
                    destChatSelect.add(optDest);
                });

                try {
                    const sessionRes = await fetch('/api/session/load');
                    const session = await sessionRes.json();
                    if (session.success) {
                        if (session.source_id) sourceChatSelect.value = session.source_id;
                        if (session.dest_id) destChatSelect.value = session.dest_id;
                        updateProgressFromHistory();
                    }
                } catch (e) {
                    console.error('Error restoring session:', e);
                }

                try {
                    const runRes = await fetch('/api/clone/running');
                    const runData = await runRes.json();
                    if (runData.success && runData.running) {
                        cloneStatusBadge.innerText = 'Cloning';
                        cloneStatusBadge.className = 'status-badge running';
                        btnStartClone.disabled = true;
                        btnStopClone.disabled = false;
                        totalItemsCloned = parseInt(progressCounter.innerText) || 0;
                    }
                } catch (e) {
                    console.error('Error checking clone status:', e);
                }
            } else {
                const optNone = '<option value="">No channels/groups found</option>';
                sourceChatSelect.innerHTML = optNone;
                destChatSelect.innerHTML = optNone;
            }
        } catch (err) {
            addTerminalLine(`Error listing channels: ${err.message}`, 'error-line');
            sourceChatSelect.innerHTML = '<option value="">Error loading</option>';
            destChatSelect.innerHTML = '<option value="">Error loading</option>';
        }
    }

    async function updateProgressFromHistory() {
        const source_id = sourceChatSelect.value;
        const destination_id = destChatSelect.value;
        if (!source_id || !destination_id || source_id === destination_id) {
            progressCounter.innerText = '0';
            return;
        }
        try {
            const res = await fetch(`/api/clone/progress?source_id=${source_id}&dest_id=${destination_id}`);
            const data = await res.json();
            if (data.success) {
                progressCounter.innerText = data.count;
            }
        } catch (e) {
            console.error('Error fetching progress:', e);
        }
    }

    function saveSession() {
        const source_id = sourceChatSelect.value;
        const dest_id = destChatSelect.value;
        fetch('/api/session/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_id, dest_id })
        }).catch(e => console.error('Error saving session:', e));
    }

    sourceChatSelect.addEventListener('change', () => { saveSession(); updateProgressFromHistory(); });
    destChatSelect.addEventListener('change', () => { saveSession(); updateProgressFromHistory(); });

    function setupSSE() {
        if (eventSource) {
            eventSource.close();
        }
        
        eventSource = new EventSource('/api/events');
        
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === 'log') {
                let styleType = 'system-line';
                if (data.data.includes('✓') || data.data.includes('SUCCESS') || data.data.includes('cloned successfully') || data.data.includes('complete')) {
                    styleType = 'success-line';
                } else if (data.data.includes('Error') || data.data.includes('failed') || data.data.includes('broken item')) {
                    styleType = 'error-line';
                } else if (data.data.includes('[Copying]') || data.data.includes('Sending')) {
                    styleType = 'copy-line';
                } else if (data.data.includes('warning') || data.data.includes('Rate limit')) {
                    styleType = 'warning-line';
                }
                
                addTerminalLine(data.data, styleType);
            }
            
            else if (data.type === 'progress') {
                totalItemsCloned = data.data.count;
                progressCounter.innerText = totalItemsCloned;
                currentActionLabel.innerText = `Copying: ${data.data.current} (${data.data.topic})`;
                
                const percentage = Math.min((totalItemsCloned * 4) % 101, 100); 
                progressBar.style.width = `${percentage}%`;
            }
            
            else if (data.type === 'clone_status') {
                if (data.data.status === 'stopped' || data.data.status === 'completed' || data.data.status === 'error') {
                    cloneStatusBadge.innerText = 'Stopped';
                    cloneStatusBadge.className = 'status-badge idle';
                    btnStartClone.disabled = false;
                    btnStopClone.disabled = true;
                    progressBar.style.width = '0%';
                }
            }
        };

        eventSource.onerror = (err) => {
            console.error('SSE Error:', err);
            eventSource.close();
            setTimeout(setupSSE, 5000);
        };
    }

    configForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const api_id = apiIdInput.value;
        const api_hash = apiHashInput.value.trim();
        
        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_id, api_hash })
            });
            const data = await res.json();
            
            if (data.success) {
                addTerminalLine('API credentials saved successfully!', 'success-line');
                checkStatus();
            } else {
                alert(`Error: ${data.error}`);
            }
        } catch (err) {
            alert('Connection error with the server.');
        }
    });

    phoneForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const phone = phoneInput.value.trim();
        addTerminalLine(`Requesting verification code for: ${phone}...`);
        
        try {
            const res = await fetch('/api/auth/phone', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone })
            });
            const data = await res.json();
            
            if (data.success) {
                showStep('step-code');
            } else {
                alert(`Error: ${data.error}`);
            }
        } catch (err) {
            alert('Network error.');
        }
    });

    codeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const code = verificationCodeInput.value.trim();
        addTerminalLine('Submitting verification code...');
        
        try {
            const res = await fetch('/api/auth/code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code })
            });
            const data = await res.json();
            
            if (data.success) {
                if (data.status === 'authorized') {
                    checkStatus();
                } else if (data.status === '2fa_required') {
                    showStep('step-password');
                }
            } else {
                alert(`Error: ${data.error}`);
            }
        } catch (err) {
            alert('Network error.');
        }
    });

    passwordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const password = passwordInput.value;
        addTerminalLine('Verifying 2FA password...');
        
        try {
            const res = await fetch('/api/auth/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password })
            });
            const data = await res.json();
            
            if (data.success) {
                checkStatus();
            } else {
                alert(`Incorrect password: ${data.error}`);
            }
        } catch (err) {
            alert('Network error.');
        }
    });

    backToPhoneBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            showStep('step-phone');
        });
    });

    btnRefreshChats.addEventListener('click', () => {
        addTerminalLine('Refreshing channels list...');
        loadChats();
    });

    btnLogout.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to disconnect and switch accounts?')) {
            return;
        }
        
        addTerminalLine('Logging out and clearing session...');
        try {
            const res = await fetch('/api/auth/logout', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                checkStatus();
            } else {
                alert('Error logging out.');
            }
        } catch (err) {
            alert('Network error.');
        }
    });

    btnStartClone.addEventListener('click', async () => {
        const source_id = sourceChatSelect.value;
        const destination_id = destChatSelect.value;
        
        if (!source_id || !destination_id) {
            alert('Please select both Source and Destination channels.');
            return;
        }
        
        if (source_id === destination_id) {
            alert('Source and Destination channels cannot be the same.');
            return;
        }

        try {
            const res = await fetch('/api/clone/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source_id,
                    destination_id,
                    blocked_words: blockedWordsInput.value.trim(),
                    skip_links: skipLinksCheckbox.checked,
                    clone_text: cloneTextCheckbox.checked,
                    clone_media: cloneMediaCheckbox.checked
                })
            });
            const data = await res.json();
            
            if (data.success) {
                cloneStatusBadge.innerText = 'Cloning';
                cloneStatusBadge.className = 'status-badge running';
                btnStartClone.disabled = true;
                btnStopClone.disabled = false;
                totalItemsCloned = parseInt(progressCounter.innerText) || 0;
                progressBar.style.width = '0%';
            } else {
                alert(`Failed to start: ${data.error}`);
            }
        } catch (err) {
            alert('Network error.');
        }
    });

    btnStopClone.addEventListener('click', async () => {
        try {
            await fetch('/api/clone/stop', { method: 'POST' });
        } catch (err) {
            console.error('Error stopping clone:', err);
        }
    });

    checkStatus();
    setupSSE();
});
