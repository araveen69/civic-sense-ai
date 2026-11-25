
// Global utility scripts can go here
console.log("CivicSense AI System Loaded");

const assistantLauncher = document.getElementById('assistantLauncher');
const assistantPanel = document.getElementById('assistantPanel');
const assistantClose = document.querySelector('.assistant-close');
const assistantForm = document.getElementById('assistantForm');
const assistantQuestion = document.getElementById('assistantQuestion');
const assistantMessages = document.getElementById('assistantMessages');

if (assistantLauncher && assistantPanel && assistantForm && assistantQuestion && assistantMessages) {
  const setAssistantOpen = (isOpen) => {
    assistantPanel.hidden = !isOpen;
    assistantPanel.setAttribute('aria-hidden', String(!isOpen));
    assistantLauncher.setAttribute('aria-expanded', String(isOpen));
    if (isOpen) assistantQuestion.focus();
  };

  const addAssistantMessage = (text, className) => {
    const message = document.createElement('div');
    message.className = `assistant-message ${className}`;
    message.textContent = text;
    assistantMessages.appendChild(message);
    assistantMessages.scrollTop = assistantMessages.scrollHeight;
    return message;
  };

  assistantLauncher.addEventListener('click', () => {
    setAssistantOpen(assistantPanel.hidden);
  });
  assistantClose?.addEventListener('click', () => {
    setAssistantOpen(false);
    assistantLauncher.focus();
  });

  assistantQuestion.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      assistantForm.requestSubmit();
    }
  });

  assistantForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = assistantQuestion.value.trim();
    if (!question) return;

    addAssistantMessage(question, 'assistant-user');
    assistantQuestion.value = '';
    const sendButton = assistantForm.querySelector('button[type="submit"]');
    sendButton.disabled = true;
    const loadingMessage = addAssistantMessage('Thinking...', 'assistant-reply');

    try {
      const response = await fetch(assistantForm.dataset.url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question})
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'The assistant could not answer right now.');
      }
      loadingMessage.textContent = data.answer;
    } catch (error) {
      loadingMessage.textContent = error.message || 'Unable to reach the assistant. Please try again.';
    } finally {
      sendButton.disabled = false;
      assistantQuestion.focus();
      assistantMessages.scrollTop = assistantMessages.scrollHeight;
    }
  });
}

window.CivicSenseLocation = {
  request(onProgress, onSuccess, onError) {
    if (!navigator.geolocation) {
      onError({code: 'unsupported'});
      return;
    }
    if (window.isSecureContext === false) {
      onError({code: 'insecure'});
      return;
    }

    let bestPosition = null;
    let watchId = null;
    let timeoutId;
    let finished = false;
    const targetAccuracy = 75;

    const stopWatching = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(timeoutId);
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    };
    const complete = (position, isPrecise) => {
      stopWatching();
      onSuccess(position, isPrecise);
    };
    const fail = (error) => {
      if (bestPosition) {
        complete(bestPosition, false);
        return;
      }
      stopWatching();
      onError(error);
    };

    watchId = navigator.geolocation.watchPosition(
      (position) => {
        if (!bestPosition || position.coords.accuracy < bestPosition.coords.accuracy) {
          bestPosition = position;
          onProgress(position);
        }
        if (position.coords.accuracy <= targetAccuracy) {
          complete(position, true);
        }
      },
      fail,
      {enableHighAccuracy: true, maximumAge: 0}
    );
    timeoutId = window.setTimeout(() => fail({code: 3}), 25000);
  },

  errorMessage(error) {
    if (error.code === 'unsupported') {
      return 'Location services are not supported by this browser.';
    }
    if (error.code === 'insecure') {
      return 'Location access requires a secure connection (HTTPS) or localhost.';
    }
    if (error.code === 1) {
      return 'Location permission was denied. Allow location access in your browser settings and try again.';
    }
    if (error.code === 2) {
      return 'Your device could not determine a location. Turn on device Location Services and try again.';
    }
    return 'No location fix was received. Check device Location Services, then retry outdoors or enter the address manually.';
  }
};