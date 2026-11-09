const chat = document.getElementById('chat');
const form = document.getElementById('chatForm');
const messageInput = document.getElementById('message');
const welcomeMarkup = chat.innerHTML;
const newChatButton = document.getElementById('newChatButton');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebar = document.querySelector('.sidebar');
const conversationList = document.getElementById('conversationList');
const storageStatus = document.getElementById('storageStatus');
const documentInput = document.getElementById('documentInput');
const documentList = document.getElementById('documentList');
const documentStatus = document.getElementById('documentStatus');
const dictateButton = document.getElementById('dictateButton');
const dictationStatus = document.getElementById('dictationStatus');
const authGate = document.getElementById('authGate');
const appShell = document.getElementById('appShell');
const authForm = document.getElementById('authForm');
const verifyForm = document.getElementById('verifyForm');
const authName = document.getElementById('authName');
const authEmail = document.getElementById('authEmail');
const authPassword = document.getElementById('authPassword');
const authTitle = document.getElementById('authTitle');
const authSubtitle = document.getElementById('authSubtitle');
const authStatus = document.getElementById('authStatus');
const authSubmit = document.getElementById('authSubmit');
const authSwitch = document.getElementById('authSwitch');
const authSwitchLabel = document.getElementById('authSwitchLabel');
const googleLogin = document.getElementById('googleLogin');
const resendVerification = document.getElementById('resendVerification');
const verifyCode = document.getElementById('verifyCode');
const authDivider = document.querySelector('.auth-divider');
const accountEmail = document.getElementById('accountEmail');
const logoutButton = document.getElementById('logoutButton');
let conversations = [];
let activeConversationId = null;
let authMode = 'login';
let verificationEmail = '';
let activeUtterance = null;
let speechRecognition = null;
let dictationBaseValue = '';
let dictationFinalTranscript = '';

async function requestJson(url, options={}){
  const response = await fetch(url, options);
  let data = {};
  if(response.status !== 204){
    try{
      data = await response.json();
    }catch(error){
      if(response.ok) throw new Error('The server returned an invalid response.');
    }
  }
  if(!response.ok) throw new Error(data.detail || `Request failed (${response.status}).`);
  return data;
}

function setAuthStatus(message, isError=false){
  authStatus.textContent = message;
  authStatus.hidden = !message;
  authStatus.classList.toggle('is-error', isError);
}

function setAuthMode(mode){
  authMode = mode;
  verifyForm.hidden = true;
  authForm.hidden = false;
  googleLogin.hidden = false;
  authDivider.hidden = false;
  authSwitch.closest('.auth-switch').hidden = false;
  resendVerification.hidden = true;
  authTitle.textContent = mode === 'register' ? 'Create your account' : 'Welcome back';
  authSubtitle.textContent = mode === 'register'
    ? 'Create a private workspace for your chats and documents.'
    : 'Sign in to continue to your private workspace.';
  document.getElementById('nameField').hidden = mode !== 'register';
  authPassword.autocomplete = mode === 'register' ? 'new-password' : 'current-password';
  authSubmit.textContent = mode === 'register' ? 'Create account' : 'Sign in';
  authSwitchLabel.textContent = mode === 'register' ? 'Already have an account?' : 'New to Aurelia?';
  authSwitch.textContent = mode === 'register' ? 'Sign in' : 'Create an account';
  authSwitch.dataset.mode = mode === 'register' ? 'login' : 'register';
  setAuthStatus('');
}

function showVerification(email, message){
  verificationEmail = email;
  authForm.hidden = true;
  verifyForm.hidden = false;
  googleLogin.hidden = true;
  authDivider.hidden = true;
  authSwitch.closest('.auth-switch').hidden = true;
  resendVerification.hidden = false;
  authTitle.textContent = 'Verify your email';
  authSubtitle.textContent = `Enter the verification token for ${email}.`;
  verifyCode.value = '';
  setAuthStatus(message);
  verifyCode.focus();
}

async function loadAuthenticatedWorkspace(){
  const session = await requestJson('/auth/session');
  accountEmail.textContent = session.user.email;
  authGate.hidden = true;
  appShell.inert = false;
  try{
    await Promise.all([loadConversations(), loadDocuments()]);
  }catch(error){
    storageStatus.textContent = 'Your saved conversations could not be loaded. Refresh the page to try again.';
    storageStatus.hidden = false;
    console.error('Could not load account conversations.', error);
  }
  renderActiveConversation();
}

function showSignedOut(){
  stopSpeech();
  conversations = [];
  activeConversationId = null;
  renderActiveConversation();
  appShell.inert = true;
  authGate.hidden = false;
  accountEmail.textContent = '';
  setAuthMode('login');
}

const actionIcons = {
  copy: '<path d="M8 8V4.8A1.8 1.8 0 0 1 9.8 3h8.4A1.8 1.8 0 0 1 20 4.8v10.4a1.8 1.8 0 0 1-1.8 1.8H15"/><rect x="4" y="8" width="11" height="13" rx="1.8"/>',
  copied: '<path d="m5 12 4 4L19 6"/>',
  like: '<path d="M7 10v11H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3Zm0 0 5-8c2 0 3 2 2 4l-1 4h6a2 2 0 0 1 2 2l-1 7a2 2 0 0 1-2 2H7"/>',
  dislike: '<path d="M7 14V3H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3Zm0 0 5 8c2 0 3-2 2-4l-1-4h6a2 2 0 0 0 2-2l-1-7a2 2 0 0 0-2-2H7"/>',
  regenerate: '<path d="M20 7v5h-5"/><path d="M4.9 9A7 7 0 0 1 17 6l3 6M4 12l3 6a7 7 0 0 0 12.1-3"/>',
  read: '<path d="M3 10v4h4l5 4V6l-5 4H3Z"/><path d="M16 9a5 5 0 0 1 0 6M18.5 6.5a9 9 0 0 1 0 11"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
};

function setButtonIcon(button, icon){
  button.replaceChildren();
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.innerHTML = actionIcons[icon];
  button.appendChild(svg);
}

function makeActionButton(action, label, icon){
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `message-action ${action}-button`;
  button.dataset.action = action;
  button.setAttribute('aria-label', label);
  button.title = label;
  setButtonIcon(button, icon);
  return button;
}

function stopSpeech(){
  if('speechSynthesis' in window) window.speechSynthesis.cancel();
  activeUtterance = null;
}

function updateDictationButton(listening){
  dictateButton.classList.toggle('is-listening', listening);
  dictateButton.setAttribute('aria-label', listening ? 'Stop dictation' : 'Dictate message');
  dictateButton.title = listening ? 'Stop dictation' : 'Dictate message';
  dictationStatus.hidden = !listening && !dictationStatus.textContent;
  if(listening) dictationStatus.textContent = 'Listening… speak now';
}

function setupDictation(){
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!Recognition){
    dictateButton.disabled = true;
    dictateButton.title = 'Voice input is unavailable in this browser';
    dictateButton.setAttribute('aria-label', 'Voice input is unavailable');
    return;
  }

  speechRecognition = new Recognition();
  speechRecognition.lang = navigator.language || 'en-US';
  speechRecognition.continuous = false;
  speechRecognition.interimResults = true;
  speechRecognition.onstart = ()=>updateDictationButton(true);
  speechRecognition.onresult = (event)=>{
    let finalText = '';
    let interimText = '';
    for(let index = event.resultIndex; index < event.results.length; index += 1){
      const transcript = event.results[index][0].transcript;
      if(event.results[index].isFinal) finalText += transcript;
      else interimText += transcript;
    }
    dictationFinalTranscript += finalText;
    messageInput.value = `${dictationBaseValue}${dictationBaseValue && dictationFinalTranscript ? ' ' : ''}${dictationFinalTranscript}${interimText}`;
    messageInput.dispatchEvent(new Event('input', {bubbles:true}));
  };
  speechRecognition.onerror = (event)=>{
    const message = event.error === 'not-allowed'
      ? 'Allow microphone access to dictate.'
      : `Dictation error: ${event.error}`;
    dictationStatus.textContent = message;
    dictationStatus.hidden = false;
    if(event.error !== 'aborted') console.error(message);
  };
  speechRecognition.onend = ()=>{
    updateDictationButton(false);
    if(!dictationStatus.textContent.startsWith('Dictation error') && !dictationStatus.textContent.startsWith('Allow microphone')){
      dictationStatus.textContent = '';
      dictationStatus.hidden = true;
    }
  };
}

function setDocumentStatus(message, isError=false){
  documentStatus.textContent = message;
  documentStatus.hidden = !message;
  documentStatus.classList.toggle('is-error', isError);
}

function renderDocuments(documents){
  documentList.replaceChildren();
  if(!documents.length){
    const empty = document.createElement('div');
    empty.className = 'conversation-empty';
    empty.textContent = 'Add PDFs, Word documents, or text files to chat with them.';
    documentList.appendChild(empty);
    return;
  }
  documents.forEach((documentInfo)=>{
    const item = document.createElement('div');
    item.className = 'document-item';
    const name = document.createElement('span');
    name.className = 'document-name';
    name.textContent = documentInfo.filename;
    name.title = documentInfo.filename;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'document-remove';
    remove.dataset.documentId = documentInfo.id;
    remove.setAttribute('aria-label', `Remove ${documentInfo.filename}`);
    remove.title = `Remove ${documentInfo.filename}`;
    remove.textContent = '×';
    item.append(name, remove);
    documentList.appendChild(item);
  });
}

async function loadDocuments(){
  try{
    const response = await fetch('/documents');
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail || 'Could not load documents.');
    renderDocuments(data.documents);
    setDocumentStatus('');
  }catch(error){
    documentList.replaceChildren();
    setDocumentStatus(String(error), true);
  }
}

async function uploadDocuments(files){
  for(const file of files){
    const formData = new FormData();
    formData.append('file', file);
    setDocumentStatus(`Adding ${file.name}…`);
    try{
      const response = await fetch('/documents', {method:'POST', body:formData});
      const data = await response.json();
      if(!response.ok) throw new Error(data.detail || `Could not add ${file.name}.`);
    }catch(error){
      setDocumentStatus(String(error), true);
      documentInput.value = '';
      await loadDocuments();
      return;
    }
  }
  documentInput.value = '';
  await loadDocuments();
  if(files.length) setDocumentStatus(`${files.length} document${files.length === 1 ? '' : 's'} added.`);
}

documentInput.addEventListener('change', ()=>void uploadDocuments([...documentInput.files]));

documentList.addEventListener('click', async (event)=>{
  const button = event.target.closest('.document-remove');
  if(!button) return;
  button.disabled = true;
  try{
    const response = await fetch(`/documents/${encodeURIComponent(button.dataset.documentId)}`, {method:'DELETE'});
    const data = response.status === 204 ? {} : await response.json();
    if(!response.ok) throw new Error(data.detail || 'Could not remove document.');
    setDocumentStatus('Document removed.');
    await loadDocuments();
  }catch(error){
    setDocumentStatus(String(error), true);
    button.disabled = false;
  }
});

setupDictation();
dictateButton.addEventListener('click', ()=>{
  if(!speechRecognition) return;
  if(dictateButton.classList.contains('is-listening')){
    speechRecognition.stop();
    return;
  }
  dictationBaseValue = messageInput.value.trim();
  dictationFinalTranscript = '';
  dictationStatus.textContent = '';
  dictationStatus.hidden = true;
  try{
    speechRecognition.start();
  }catch(error){
    dictationStatus.textContent = 'Dictation could not start. Try again.';
    dictationStatus.hidden = false;
    console.error('Could not start speech recognition.', error);
  }
});

async function loadConversations(){
  const data = await requestJson('/conversations');
  conversations = data.conversations.map((item)=>({
    ...item,
    messages: Array.isArray(item.messages) ? item.messages : [],
    history: Array.isArray(item.history) ? item.history : [],
    updatedAt: Number(item.updatedAt) || Date.now(),
  }));
  activeConversationId = null;
}

async function saveConversation(conversation){
  const saved = await requestJson(`/conversations/${encodeURIComponent(conversation.id)}`, {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      title: conversation.title,
      messages: conversation.messages,
      history: conversation.history,
    }),
  });
  Object.assign(conversation, saved);
}

function showPersistenceError(error){
  storageStatus.textContent = 'This change could not be saved to your account. Check your connection and try again.';
  storageStatus.hidden = false;
  console.error('Could not save account conversation.', error);
}

authSwitch.addEventListener('click', ()=>setAuthMode(authSwitch.dataset.mode));

googleLogin.addEventListener('click', ()=>{
  window.location.assign('/auth/google/login');
});

authForm.addEventListener('submit', async (event)=>{
  event.preventDefault();
  authSubmit.disabled = true;
  setAuthStatus('');
  const payload = {
    email: authEmail.value.trim(),
    password: authPassword.value,
  };
  if(authMode === 'register') payload.name = authName.value.trim();
  try{
    if(authMode === 'register'){
      const result = await requestJson('/auth/register', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
      showVerification(payload.email, result.message);
    }else{
      await requestJson('/auth/login', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
      await loadAuthenticatedWorkspace();
    }
  }catch(error){
    if(authMode === 'login' && error.message === 'Verify your email before signing in.'){
      verificationEmail = payload.email;
      resendVerification.hidden = false;
    }
    setAuthStatus(String(error.message || error), true);
  }finally{
    authSubmit.disabled = false;
  }
});

verifyForm.addEventListener('submit', async (event)=>{
  event.preventDefault();
  const submitButton = verifyForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try{
    await requestJson('/auth/verify-email', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:verifyCode.value.trim()}),
    });
    setAuthMode('login');
    authEmail.value = verificationEmail;
    setAuthStatus('Email verified. Sign in to open your private workspace.');
    authPassword.focus();
  }catch(error){
    setAuthStatus(String(error.message || error), true);
  }finally{
    submitButton.disabled = false;
  }
});

resendVerification.addEventListener('click', async ()=>{
  resendVerification.disabled = true;
  try{
    const result = await requestJson('/auth/verification/resend', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:verificationEmail}),
    });
    setAuthStatus(result.message);
  }catch(error){
    setAuthStatus(String(error.message || error), true);
  }finally{
    resendVerification.disabled = false;
  }
});

logoutButton.addEventListener('click', async ()=>{
  logoutButton.disabled = true;
  try{
    await requestJson('/auth/logout', {method:'POST'});
  }catch(error){
    console.error('Could not revoke the sign-out session.', error);
  }finally{
    logoutButton.disabled = false;
    showSignedOut();
  }
});

fetch('/auth/session')
  .then(async (response)=>{
    if(response.status === 401){
      setAuthMode('login');
      return;
    }
    if(!response.ok) throw new Error(`Session check failed (${response.status}).`);
    await loadAuthenticatedWorkspace();
  })
  .catch((error)=>{
    setAuthMode('login');
    setAuthStatus('Could not check your sign-in session. Refresh the page to try again.', true);
    console.error('Could not restore Aurelia session.', error);
  });

fetch('/health')
  .then(async (response)=>{
    if(!response.ok) throw new Error('Health check failed');
    const status = await response.json();
    const modelStatus = document.getElementById('modelStatus');
    if(status.model_status === 'ready'){
      modelStatus.textContent = `Model ready: ${status.model}`;
    } else if(status.model_status === 'model_missing'){
      modelStatus.textContent = `Model unavailable: ${status.model}`;
    } else {
      modelStatus.textContent = 'Model server unavailable';
    }
  })
  .catch(()=>{
    document.getElementById('modelStatus').textContent = 'Model status unavailable';
  });

function now(){
  return new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function addMessage(role, text, timestamp=now(), messageIndex=-1, feedback=null, citations=[]){
  document.getElementById('emptyState')?.remove();
  const div = document.createElement('div');
  div.className = 'message ' + role;
  if(messageIndex >= 0) div.dataset.messageIndex = String(messageIndex);
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  if(role === 'assistant' && citations.length){
    const sourceList = document.createElement('div');
    sourceList.className = 'message-sources';
    const heading = document.createElement('span');
    heading.className = 'message-sources-label';
    heading.textContent = 'Sources';
    sourceList.appendChild(heading);
    citations.forEach((citation)=>{
      const source = document.createElement('span');
      source.className = 'source-chip';
      source.textContent = citation.page ? `${citation.filename} · p. ${citation.page}` : citation.filename;
      source.title = citation.quote || citation.filename;
      sourceList.appendChild(source);
    });
    div.appendChild(sourceList);
  }
  const info = document.createElement('div');
  info.className = 'msg-info';
  info.textContent = typeof timestamp === 'number'
    ? new Date(timestamp).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})
    : timestamp;
  div.appendChild(bubble);
  div.appendChild(info);
  if(role === 'assistant'){
    const toolbar = document.createElement('div');
    toolbar.className = 'message-toolbar';
    toolbar.appendChild(makeActionButton('copy', 'Copy response', 'copy'));
    const likeButton = makeActionButton('like', 'Good response', 'like');
    const dislikeButton = makeActionButton('dislike', 'Bad response', 'dislike');
    likeButton.setAttribute('aria-pressed', String(feedback === 'like'));
    dislikeButton.setAttribute('aria-pressed', String(feedback === 'dislike'));
    toolbar.append(likeButton, dislikeButton);
    toolbar.appendChild(makeActionButton('regenerate', 'Regenerate response', 'regenerate'));
    if('speechSynthesis' in window){
      toolbar.appendChild(makeActionButton('read', 'Read response aloud', 'read'));
    }
    div.appendChild(toolbar);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function renderConversationList(){
  conversationList.replaceChildren();
  const orderedConversations = [...conversations].sort((a, b)=>b.updatedAt - a.updatedAt);
  if(!orderedConversations.length){
    const empty = document.createElement('div');
    empty.className = 'conversation-empty';
    empty.textContent = 'Your conversations will appear here.';
    conversationList.appendChild(empty);
    return;
  }

  orderedConversations.forEach((conversation)=>{
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'conversation-link';
    button.textContent = conversation.title;
    button.title = conversation.title;
    button.dataset.conversationId = conversation.id;
    if(conversation.id === activeConversationId) button.setAttribute('aria-current', 'true');
    conversationList.appendChild(button);
  });
}

function renderActiveConversation(){
  const conversation = conversations.find((item)=>item.id === activeConversationId);
  stopSpeech();
  chat.innerHTML = conversation ? '' : welcomeMarkup;
  if(conversation){
    conversation.messages.forEach((message, index)=>
      addMessage(message.role, message.content, message.time, index, message.feedback, message.citations || [])
    );
    updateRegenerateButtons(conversation);
  }
  renderConversationList();
}

function updateRegenerateButtons(conversation){
  let lastAssistantIndex = -1;
  for(let index = conversation.messages.length - 1; index >= 0; index -= 1){
    if(conversation.messages[index].role === 'assistant'){
      lastAssistantIndex = index;
      break;
    }
  }
  chat.querySelectorAll('.regenerate-button').forEach((button)=>{
    const messageIndex = Number(button.closest('.message')?.dataset.messageIndex);
    const hasLaterUser = conversation.messages
      .slice(messageIndex + 1)
      .some((item)=>item.role === 'user');
    button.disabled = messageIndex !== lastAssistantIndex || hasLaterUser;
  });
}

async function createConversation(firstMessage){
  const conversation = await requestJson('/conversations', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      title:firstMessage.length > 48 ? `${firstMessage.slice(0, 48).trimEnd()}…` : firstMessage,
      messages:[],
      history:[],
    }),
  });
  conversation.messages = [];
  conversation.history = [];
  conversations.push(conversation);
  activeConversationId = conversation.id;
  return conversation;
}

function addConversationMessage(conversation, role, content, metadata={}){
  conversation.messages.push({role, content, time: now(), ...metadata});
  conversation.updatedAt = Date.now();
  if(conversation.id === activeConversationId){
    addMessage(role, content, undefined, conversation.messages.length - 1, null, metadata.citations || []);
    updateRegenerateButtons(conversation);
  }
  renderConversationList();
}

function setTyping(state){
  const existing = document.querySelector('.typing');
  if(state && !existing){
    const d = document.createElement('div');
    d.className = 'message system typing';
    const b = document.createElement('div');
    b.className = 'bubble';
    b.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
    d.appendChild(b);
    chat.appendChild(d);
    chat.scrollTop = chat.scrollHeight;
  } else if(!state && existing){
    existing.remove();
  }
}

form.addEventListener('submit', async (event)=>{
  event.preventDefault();
  const message = messageInput.value.trim();
  if(!message) return;

  const submitButton = form.querySelector('.send-button');
  submitButton.disabled = true;
  let conversation = conversations.find((item)=>item.id === activeConversationId);
  try{
    if(!conversation) conversation = await createConversation(message);
  }catch(error){
    submitButton.disabled = false;
    storageStatus.textContent = 'Your conversation could not be created. Please try again.';
    storageStatus.hidden = false;
    console.error('Could not create account conversation.', error);
    return;
  }
  const conversationId = conversation.id;
  const history = [...conversation.history];
  addConversationMessage(conversation, 'user', message);
  messageInput.value = '';
  messageInput.style.height = 'auto';
  setTyping(true);

  try{
    const data = await requestJson('/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        message,
        history: history.slice(-20),
        conversation_id:conversationId,
      })
    });
    if(conversation.id === activeConversationId) setTyping(false);
    addConversationMessage(conversation, 'assistant', data.answer, {citations:data.citations || []});
    conversation.history.push({role:'user', content:message});
    conversation.history.push({role:'assistant', content:data.answer});
    conversation.history.splice(0, Math.max(0, conversation.history.length - 20));
    await saveConversation(conversation);
  }catch(error){
    if(conversation.id === activeConversationId) setTyping(false);
    addConversationMessage(conversation, 'error', error.message || String(error));
    try{
      await saveConversation(conversation);
    }catch(saveError){
      showPersistenceError(saveError);
    }
  }finally{
    submitButton.disabled = false;
  }
});

newChatButton.addEventListener('click', ()=>{
  stopSpeech();
  activeConversationId = null;
  renderActiveConversation();
  messageInput.value = '';
  messageInput.style.height = 'auto';
  messageInput.focus();
  document.body.classList.remove('sidebar-open');
});

conversationList.addEventListener('click', (event)=>{
  const button = event.target.closest('.conversation-link');
  if(!button) return;
  activeConversationId = button.dataset.conversationId;
  renderActiveConversation();
  document.body.classList.remove('sidebar-open');
});

sidebarToggle.addEventListener('click', ()=>{
  document.body.classList.toggle('sidebar-open');
});

document.querySelector('.workspace').addEventListener('click', (event)=>{
  if(event.target.closest('#sidebarToggle')) return;
  if(window.matchMedia('(max-width: 760px)').matches){
    document.body.classList.remove('sidebar-open');
  }
});

async function regenerateResponse(messageElement){
  const conversation = conversations.find((item)=>item.id === activeConversationId);
  const messageIndex = Number(messageElement.dataset.messageIndex);
  if(!conversation || !Number.isInteger(messageIndex)) return;
  let lastAssistantIndex = -1;
  for(let index = conversation.messages.length - 1; index >= 0; index -= 1){
    if(conversation.messages[index].role === 'assistant'){
      lastAssistantIndex = index;
      break;
    }
  }
  if(messageIndex !== lastAssistantIndex) return;

  let userIndex = messageIndex - 1;
  while(userIndex >= 0 && conversation.messages[userIndex].role !== 'user') userIndex -= 1;
  if(userIndex < 0) return;

  const prompt = conversation.messages[userIndex].content;
  const history = conversation.messages
    .slice(0, userIndex)
    .filter((item)=>item.role === 'user' || item.role === 'assistant')
    .map((item)=>({role:item.role, content:item.content}))
    .slice(-20);
  messageElement.querySelectorAll('.message-action').forEach((button)=>{button.disabled = true;});
  if(conversation.id === activeConversationId) setTyping(true);
  try{
    const data = await requestJson('/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        message:prompt,
        history,
        conversation_id:conversation.id,
      })
    });
    conversation.messages[messageIndex] = {
      role:'assistant',
      content:data.answer,
      time:now(),
      feedback:null,
      citations:data.citations || [],
    };
    conversation.messages.splice(messageIndex + 1);
    conversation.history = [...history, {role:'user', content:prompt}, {role:'assistant', content:data.answer}].slice(-20);
    conversation.updatedAt = Date.now();
    await saveConversation(conversation);
    renderConversationList();
    if(conversation.id === activeConversationId) renderActiveConversation();
  }catch(error){
    console.error('Could not regenerate assistant response.', error);
    addConversationMessage(conversation, 'error', String(error));
    try{
      await saveConversation(conversation);
    }catch(saveError){
      showPersistenceError(saveError);
    }
  }finally{
    if(conversation.id === activeConversationId) setTyping(false);
  }
}

chat.addEventListener('click', (event)=>{
  const actionButton = event.target.closest('.message-action');
  if(actionButton){
    const messageElement = actionButton.closest('.message.assistant');
    const responseText = messageElement?.querySelector('.bubble')?.textContent;
    const action = actionButton.dataset.action;
    if(!messageElement || !responseText) return;

    if(action === 'copy'){
      if(!navigator.clipboard?.writeText){
        actionButton.setAttribute('aria-label', 'Clipboard is unavailable');
        actionButton.title = 'Clipboard is unavailable';
        actionButton.classList.add('action-error');
        return;
      }
      navigator.clipboard.writeText(responseText)
      .then(()=>{
        setButtonIcon(actionButton, 'copied');
        actionButton.setAttribute('aria-label', 'Response copied');
        actionButton.title = 'Response copied';
        actionButton.classList.add('action-success');
        window.setTimeout(()=>{
          if(!actionButton.isConnected) return;
          setButtonIcon(actionButton, 'copy');
          actionButton.setAttribute('aria-label', 'Copy response');
          actionButton.title = 'Copy response';
          actionButton.classList.remove('action-success');
        }, 1800);
      })
      .catch((error)=>{
        console.error('Could not copy assistant response to clipboard.', error);
        actionButton.setAttribute('aria-label', 'Could not copy response');
        actionButton.title = 'Could not copy response';
        actionButton.classList.add('action-error');
      });
    }else if(action === 'like' || action === 'dislike'){
      const conversation = conversations.find((item)=>item.id === activeConversationId);
      const message = conversation?.messages[Number(messageElement.dataset.messageIndex)];
      if(!message) return;
      message.feedback = message.feedback === action ? null : action;
      messageElement.querySelectorAll('.like-button, .dislike-button').forEach((button)=>{
        button.setAttribute('aria-pressed', String(button.dataset.action === message.feedback));
      });
      void saveConversation(conversation).catch(showPersistenceError);
    }else if(action === 'regenerate'){
      void regenerateResponse(messageElement);
    }else if(action === 'read'){
      if(activeUtterance && window.speechSynthesis.speaking){
        stopSpeech();
        setButtonIcon(actionButton, 'read');
        actionButton.setAttribute('aria-label', 'Read response aloud');
        actionButton.title = 'Read response aloud';
      }else{
        stopSpeech();
        activeUtterance = new SpeechSynthesisUtterance(responseText);
        activeUtterance.onend = ()=>{
          activeUtterance = null;
          if(actionButton.isConnected){
            setButtonIcon(actionButton, 'read');
            actionButton.setAttribute('aria-label', 'Read response aloud');
            actionButton.title = 'Read response aloud';
          }
        };
        activeUtterance.onerror = (error)=>{
          console.error('Could not read assistant response aloud.', error);
          activeUtterance = null;
          if(actionButton.isConnected){
            setButtonIcon(actionButton, 'read');
            actionButton.setAttribute('aria-label', 'Read response aloud');
            actionButton.title = 'Read response aloud';
          }
        };
        setButtonIcon(actionButton, 'stop');
        actionButton.setAttribute('aria-label', 'Stop reading response');
        actionButton.title = 'Stop reading response';
        window.speechSynthesis.speak(activeUtterance);
      }
    }
    return;
  }

  const suggestion = event.target.closest('.suggestion');
  if(!suggestion) return;
  messageInput.value = suggestion.dataset.prompt || '';
  form.requestSubmit();
});

sidebar.addEventListener('click', (event)=>{
  const topic = event.target.closest('.topic-button');
  if(!topic) return;
  messageInput.value = topic.dataset.prompt || '';
  document.body.classList.remove('sidebar-open');
  form.requestSubmit();
});

renderActiveConversation();

messageInput.addEventListener('keydown', (event)=>{
  if(event.key === 'Enter' && !event.shiftKey){
    event.preventDefault();
    form.requestSubmit();
  }
});

messageInput.addEventListener('input', ()=>{
  messageInput.style.height = 'auto';
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
});
