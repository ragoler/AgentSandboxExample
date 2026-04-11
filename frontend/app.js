document.addEventListener('DOMContentLoaded', () => {
    const grid = document.getElementById('sandbox-grid');
    const createBtn = document.getElementById('create-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const modal = document.getElementById('modal');
    const closeModal = document.getElementById('close-modal');
    const sendBtn = document.getElementById('send-btn');
    const quoteBtn = document.getElementById('quote-btn');
    const messageInput = document.getElementById('message-input');
    const chatArea = document.getElementById('chat-area');
    const modalTitle = document.getElementById('modal-title');

    let activeSandboxId = null;
    const lastMessages = {}; // Store last message per sandbox
    let isInitialLoad = true;

    async function fetchSandboxes() {
        if (isInitialLoad) {
            grid.innerHTML = '<div class="card skeleton">Loading sandboxes...</div>';
            isInitialLoad = false;
        }

        // Save inputs to prevent losing text during re-render
        const savedInputs = {};
        document.querySelectorAll('input[type="text"]').forEach(input => {
            savedInputs[input.id] = input.value;
        });

        try {
            const response = await fetch('/api/sandboxes');
            const data = await response.json();
            renderSandboxes(data);

            // Restore inputs
            Object.keys(savedInputs).forEach(id => {
                const input = document.getElementById(id);
                if (input) input.value = savedInputs[id];
            });
        } catch (error) {
            if (grid.innerHTML === '') {
                grid.innerHTML = '<div class="card error">Failed to load sandboxes.</div>';
            }
            console.error(error);
        }
    }

    function renderSandboxes(sandboxes) {
        grid.innerHTML = '';
        if (sandboxes.length === 0) {
            grid.innerHTML = '<div class="card">No sandboxes found. Create one!</div>';
            return;
        }

        sandboxes.forEach(sb => {
            const card = document.createElement('div');
            card.className = 'card';
            const isProvisioning = sb.status === 'Provisioning';
            card.innerHTML = `
                <h3>Sandbox: ${sb.sandbox_id}</h3>
                <div class="card-row status-row">
                    <div class="status ${sb.status.toLowerCase()}">${sb.status}</div>
                    <div class="input-group compact">
                        <input type="text" id="input-${sb.sandbox_id}" placeholder="Message..." ${isProvisioning ? 'disabled' : ''}>
                        <button class="btn primary send-btn" data-id="${sb.sandbox_id}" ${isProvisioning ? 'disabled' : ''}>Send</button>
                    </div>
                </div>
                <div class="card-actions">
                    <button class="btn secondary sleep-btn" data-id="${sb.sandbox_id}" ${sb.status === 'Sleeping' || isProvisioning ? 'disabled' : ''}>Sleep</button>
                    <button class="btn secondary wake-btn" data-id="${sb.sandbox_id}" ${sb.status === 'Running' || isProvisioning ? 'disabled' : ''}>Wake</button>
                    <button class="btn secondary quote-btn" data-id="${sb.sandbox_id}" ${isProvisioning ? 'disabled' : ''}>Quote</button>
                    <button class="btn danger delete-btn" data-id="${sb.sandbox_id}">Delete</button>
                </div>
                <div class="last-message-area" id="last-message-${sb.sandbox_id}">
                    <span class="label">Last Message:</span>
                    <span class="content" id="message-content-${sb.sandbox_id}">${lastMessages[sb.sandbox_id] || 'None'}</span>
                </div>
            `;
            grid.appendChild(card);
        });

        // Add event listeners to card buttons
        document.querySelectorAll('.sleep-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.dataset.id;
                await fetch(`/api/sandboxes/${id}/sleep`, { method: 'POST' });
                fetchSandboxes();
            });
        });

        document.querySelectorAll('.wake-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.dataset.id;
                await fetch(`/api/sandboxes/${id}/wake`, { method: 'POST' });
                fetchSandboxes();
            });
        });

        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.dataset.id;
                await fetch(`/api/sandboxes/${id}`, { method: 'DELETE' });
                fetchSandboxes();
            });
        });

        document.querySelectorAll('.send-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.dataset.id;
                const input = document.getElementById(`input-${id}`);
                const messageContent = document.getElementById(`message-content-${id}`);
                
                if (!input.value) return;
                
                const message = input.value;
                input.value = '';
                
                try {
                    const response = await fetch(`/api/sandboxes/${id}/message`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message })
                    });
                    const data = await response.json();
                    lastMessages[id] = data.reply;
                    fetchSandboxes(); // Refresh status card
                } catch (error) {
                    messageContent.textContent = 'Error: Failed to send message.';
                }
            });
        });

        document.querySelectorAll('.quote-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = e.target.dataset.id;
                const messageContent = document.getElementById(`message-content-${id}`);
                
                try {
                    const response = await fetch(`/api/sandboxes/${id}/quote`);
                    const data = await response.json();
                    lastMessages[id] = `Quote: ${data.quote}`;
                    fetchSandboxes(); // Refresh status card
                } catch (error) {
                    messageContent.textContent = 'Error: Failed to get quote.';
                }
            });
        });
    }

    createBtn.addEventListener('click', async () => {
        try {
            await fetch('/api/sandboxes', { method: 'POST' });
            fetchSandboxes();
        } catch (error) {
            console.error("Failed to create sandbox", error);
        }
    });

    refreshBtn.addEventListener('click', fetchSandboxes);

    function appendMessage(area, sender, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;
        msgDiv.textContent = text;
        area.appendChild(msgDiv);
        area.scrollTop = area.scrollHeight; // Scroll to bottom
    }

    // Initial load
    fetchSandboxes();

    // Poll for updates every 5 seconds
    setInterval(fetchSandboxes, 5000);
});

