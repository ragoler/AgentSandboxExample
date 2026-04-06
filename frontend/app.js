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

    async function fetchSandboxes() {
        grid.innerHTML = '<div class="card skeleton">Loading sandboxes...</div>';
        try {
            const response = await fetch('/api/sandboxes');
            const data = await response.json();
            renderSandboxes(data);
        } catch (error) {
            grid.innerHTML = '<div class="card error">Failed to load sandboxes.</div>';
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
            card.innerHTML = `
                <h3>Sandbox: ${sb.sandbox_id}</h3>
                <div class="status ${sb.status.toLowerCase()}">${sb.status}</div>
                <div class="card-actions">
                    <button class="btn secondary interact-btn" data-id="${sb.sandbox_id}">Interact</button>
                    <button class="btn secondary sleep-btn" data-id="${sb.sandbox_id}" ${sb.status === 'Sleeping' ? 'disabled' : ''}>Sleep</button>
                    <button class="btn secondary wake-btn" data-id="${sb.sandbox_id}" ${sb.status === 'Running' ? 'disabled' : ''}>Wake</button>
                </div>
            `;
            grid.appendChild(card);
        });

        // Add event listeners to card buttons
        document.querySelectorAll('.interact-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                activeSandboxId = e.target.dataset.id;
                modalTitle.textContent = `Interact with ${activeSandboxId}`;
                chatArea.innerHTML = ''; // Clear previous chat
                modal.classList.add('visible');
            });
        });

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

    closeModal.addEventListener('click', () => {
        modal.classList.remove('visible');
        activeSandboxId = null;
    });

    sendBtn.addEventListener('click', async () => {
        if (!activeSandboxId || !messageInput.value) return;

        const message = messageInput.value;
        appendMessage('user', message);
        messageInput.value = '';

        try {
            const response = await fetch(`/api/sandboxes/${activeSandboxId}/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            const data = await response.json();
            appendMessage('sandbox', data.reply);
        } catch (error) {
            appendMessage('sandbox', 'Error: Failed to send message.');
        }
    });

    quoteBtn.addEventListener('click', async () => {
        if (!activeSandboxId) return;

        try {
            const response = await fetch(`/api/sandboxes/${activeSandboxId}/quote`);
            const data = await response.json();
            appendMessage('sandbox', `Quote: ${data.quote}`);
        } catch (error) {
            appendMessage('sandbox', 'Error: Failed to get quote.');
        }
    });

    function appendMessage(sender, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;
        msgDiv.textContent = text;
        chatArea.appendChild(msgDiv);
        chatArea.scrollTop = chatArea.scrollHeight; // Scroll to bottom
    }

    // Initial load
    fetchSandboxes();
});
