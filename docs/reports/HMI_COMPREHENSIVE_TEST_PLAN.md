# Local Lucy v8 - Comprehensive HMI Test Plan

## Pre-Test Setup
1. Ensure Ollama is running: `ollama serve`
2. Ensure local-lucy model exists: `ollama list | grep local-lucy`
3. Clear previous logs: `rm -f ~/lucy-v8/logs/*.log`

## Test Categories

### 1. Launch & Smoke Tests
- [ ] HMI launches without errors
- [ ] Window title shows "Local Lucy v8"
- [ ] Version indicator visible
- [ ] Status panel initializes

### 2. Interface Level Tests (3-Level Structure)
- [ ] **Simple Mode**: Default view, clean UI, Voice PTT visible
- [ ] **Power Mode**: Route summary, health status, decision trace visible
- [ ] **Engineering Mode**: Full diagnostics, event logs, raw traces visible
- [ ] Level switching works smoothly

### 3. Voice PTT Tests
- [ ] "Hold to Talk" button visible in Simple mode
- [ ] Button state changes on press/hold
- [ ] Voice recording activates
- [ ] Transcription appears in chat

### 4. Python Router Tests
- [ ] LOCAL route (bypass) works
- [ ] AUGMENTED route with evidence works
- [ ] Latency profiling outputs visible in logs
- [ ] No shell fallback (Python handles errors natively)

### 5. Conversation Tests
- [ ] Text input works
- [ ] Response displays correctly
- [ ] Conversation history maintained
- [ ] Context footer appears for unverified sources

### 6. Creative Writing (Force Local)
- [ ] Creative prompts forced to LOCAL route
- [ ] No identity prefix in responses
- [ ] No truncation in long responses

### 7. Evidence & Routing
- [ ] Medical context detection works
- [ ] Evidence fetching triggers appropriately
- [ ] Source markers stripped from responses

### 8. Error Handling
- [ ] Graceful error messages
- [ ] No crashes on edge cases
- [ ] Proper error reporting in UI
