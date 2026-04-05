// caption-editor.js - Visual Caption Editor
console.log("✅ Caption Editor loaded");

// Get URL parameters
const urlParams = new URLSearchParams(window.location.search);
const jobId = urlParams.get('job');
const clipIdx = parseInt(urlParams.get('clip'));

if (!jobId || isNaN(clipIdx)) {
  alert('Invalid parameters. Missing job ID or clip index.');
  window.location.href = '/';
}

// DOM elements
const videoPlayer = document.getElementById('videoPlayer');
const currentCaption = document.getElementById('currentCaption');
const timelineSlider = document.getElementById('timelineSlider');
const currentTimeEl = document.getElementById('currentTime');
const durationEl = document.getElementById('duration');
const wordsTimeline = document.getElementById('wordsTimeline');
const playPauseBtn = document.getElementById('playPauseBtn');
const backBtn = document.getElementById('backBtn');
const saveBtn = document.getElementById('saveBtn');
const resetBtn = document.getElementById('resetBtn');
const wordEditor = document.getElementById('wordEditor');
const wordText = document.getElementById('wordText');
const wordStart = document.getElementById('wordStart');
const wordEnd = document.getElementById('wordEnd');
const updateWordBtn = document.getElementById('updateWordBtn');
const cancelEditBtn = document.getElementById('cancelEditBtn');

// State
let words = [];
let originalWords = [];
let currentWordIndex = -1;
let isPlaying = false;
let videoDuration = 0;

// Initialize
async function init() {
  try {
    // Load video
    videoPlayer.src = `/api/jobs/${jobId}/clips/${clipIdx}/video`;

    // Load words
    await loadWords();

    // Setup video events
    setupVideoEvents();

    // Setup controls
    setupControls();

    // Render timeline
    renderTimeline();

  } catch (error) {
    console.error('Failed to initialize editor:', error);
    alert('Failed to load caption editor. Please try again.');
  }
}

// Load words data
async function loadWords() {
  const response = await fetch(`/api/jobs/${jobId}/clips/${clipIdx}/words`, {
    credentials: 'include'
  });

  if (!response.ok) {
    throw new Error('Failed to load words');
  }

  const data = await response.json();
  words = (data.words || []).map((w, index) => ({
    ...w,
    index,
    start: parseFloat(w.start || 0),
    end: parseFloat(w.end || 0)
  }));

  // Store original copy for reset functionality
  originalWords = JSON.parse(JSON.stringify(words));
}

// Setup video event listeners
function setupVideoEvents() {
  videoPlayer.addEventListener('loadedmetadata', () => {
    videoDuration = videoPlayer.duration;
    durationEl.textContent = formatTime(videoDuration);
    timelineSlider.max = videoDuration;
  });

  videoPlayer.addEventListener('timeupdate', () => {
    const currentTime = videoPlayer.currentTime;
    currentTimeEl.textContent = formatTime(currentTime);
    timelineSlider.value = currentTime;

    // Update current word highlighting
    updateCurrentWord(currentTime);
    updateCurrentCaption(currentTime);
  });

  videoPlayer.addEventListener('ended', () => {
    isPlaying = false;
    playPauseBtn.textContent = '▶️ Play';
  });
}

// Setup control event listeners
function setupControls() {
  // Timeline slider
  timelineSlider.addEventListener('input', (e) => {
    const time = parseFloat(e.target.value);
    videoPlayer.currentTime = time;
  });

  // Play/pause button
  playPauseBtn.addEventListener('click', () => {
    if (isPlaying) {
      videoPlayer.pause();
      playPauseBtn.textContent = '▶️ Play';
    } else {
      videoPlayer.play();
      playPauseBtn.textContent = '⏸️ Pause';
    }
    isPlaying = !isPlaying;
  });

  // Back button
  backBtn.addEventListener('click', () => {
    window.location.href = '/';
  });

  // Save button
  saveBtn.addEventListener('click', async () => {
    await saveChanges();
  });

  // Reset button
  resetBtn.addEventListener('click', () => {
    if (confirm('Reset all changes to original captions?')) {
      words = JSON.parse(JSON.stringify(originalWords));
      renderTimeline();
      hideWordEditor();
    }
  });

  // Word editor buttons
  updateWordBtn.addEventListener('click', () => {
    updateSelectedWord();
  });

  cancelEditBtn.addEventListener('click', () => {
    hideWordEditor();
  });
}

// Render the words timeline
function renderTimeline() {
  wordsTimeline.innerHTML = '';

  words.forEach((word, index) => {
    const segment = document.createElement('div');
    segment.className = 'word-segment';
    segment.textContent = word.word;
    segment.dataset.index = index;

    // Calculate width based on duration (rough approximation)
    const duration = word.end - word.start;
    const width = Math.max(60, duration * 50); // Minimum 60px, scale by duration
    segment.style.width = `${width}px`;

    segment.addEventListener('click', () => {
      selectWord(index);
    });

    wordsTimeline.appendChild(segment);
  });
}

// Update current word highlighting
function updateCurrentWord(currentTime) {
  // Remove current class from all segments
  document.querySelectorAll('.word-segment.current').forEach(el => {
    el.classList.remove('current');
  });

  // Find current word
  const currentWord = words.find(word => currentTime >= word.start && currentTime <= word.end);
  if (currentWord) {
    const segment = wordsTimeline.children[currentWord.index];
    if (segment) {
      segment.classList.add('current');
      // Scroll to keep current word visible
      segment.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }
}

// Update current caption display
function updateCurrentCaption(currentTime) {
  const currentWords = words.filter(word =>
    currentTime >= word.start && currentTime <= word.end
  );

  if (currentWords.length > 0) {
    currentCaption.textContent = currentWords.map(w => w.word).join(' ');
  } else {
    currentCaption.textContent = '';
  }
}

// Select a word for editing
function selectWord(index) {
  // Remove selected class from all segments
  document.querySelectorAll('.word-segment.selected').forEach(el => {
    el.classList.remove('selected');
  });

  // Add selected class to clicked segment
  const segment = wordsTimeline.children[index];
  if (segment) {
    segment.classList.add('selected');
  }

  // Show word editor
  currentWordIndex = index;
  const word = words[index];

  wordText.value = word.word;
  wordStart.value = word.start.toFixed(3);
  wordEnd.value = word.end.toFixed(3);

  wordEditor.style.display = 'block';
}

// Hide word editor
function hideWordEditor() {
  wordEditor.style.display = 'none';
  currentWordIndex = -1;

  // Remove selected class
  document.querySelectorAll('.word-segment.selected').forEach(el => {
    el.classList.remove('selected');
  });
}

// Update selected word
function updateSelectedWord() {
  if (currentWordIndex === -1) return;

  const newText = wordText.value.trim();
  const newStart = parseFloat(wordStart.value);
  const newEnd = parseFloat(wordEnd.value);

  if (!newText) {
    alert('Word text cannot be empty');
    return;
  }

  if (isNaN(newStart) || isNaN(newEnd) || newStart >= newEnd) {
    alert('Invalid start/end times');
    return;
  }

  // Update word
  words[currentWordIndex] = {
    ...words[currentWordIndex],
    word: newText,
    start: newStart,
    end: newEnd
  };

  // Re-render timeline
  renderTimeline();

  // Hide editor
  hideWordEditor();
}

// Save changes to server
async function saveChanges() {
  try {
    // Convert words back to server format
    const wordsData = words.map(word => ({
      word: word.word,
      start: word.start,
      end: word.end
    }));

    const formData = new FormData();
    formData.append('words_json', JSON.stringify({ words: wordsData }));

    const response = await fetch(`/api/jobs/${jobId}/clips/${clipIdx}/words`, {
      method: 'POST',
      credentials: 'include',
      body: formData
    });

    if (!response.ok) {
      throw new Error('Failed to save changes');
    }

    alert('Changes saved successfully!');
  } catch (error) {
    console.error('Save failed:', error);
    alert('Failed to save changes. Please try again.');
  }
}

// Utility functions
function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', init);