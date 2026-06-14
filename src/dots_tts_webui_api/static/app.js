const state = {
  config: null,
  voices: [],
  currentJobId: null,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);

function errorMessage(detail, fallback) {
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
  }
  return detail || fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      detail = errorMessage(data.detail, detail);
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function option(value, label) {
  const node = document.createElement('option');
  node.value = value;
  node.textContent = label;
  return node;
}

function fillConfig(config) {
  state.config = config;
  $('modeBadge').textContent = config.mock_tts ? 'mock 模式' : 'real 模式';
  $('silenceMs').value = config.defaults.silence_ms;
  $('chunkMinChars').value = config.defaults.chunk_min_chars;
  $('chunkMaxChars').value = config.defaults.chunk_max_chars;
  $('numSteps').value = config.defaults.num_steps;
  $('guidanceScale').value = config.defaults.guidance_scale;
  $('speakerScale').value = config.defaults.speaker_scale;
  $('seed').value = config.defaults.seed;

  $('odeMethod').replaceChildren(...config.supported_ode_methods.map((v) => option(v, v)));
  $('templateName').replaceChildren(...config.supported_template_names.map((v) => option(v, v)));
  $('templateName').value = 'tts';
  const languageOptions = [];
  for (const [name, code] of Object.entries(config.supported_languages)) {
    languageOptions.push(option(code, `${name} (${code})`));
  }
  $('language').replaceChildren(...languageOptions);
  $('language').value = 'zh';
}

async function loadVoices() {
  state.voices = await api('/api/voices');
  const options = [option('', '不使用 / No Preset'), option('__custom__', '自定义上传')];
  for (const voice of state.voices) options.push(option(voice.name, voice.name));
  $('voiceSelect').replaceChildren(...options);
  $('voiceSelect').value = '';
  updateVoiceUI();
}

function updateVoiceUI() {
  const selected = $('voiceSelect').value;
  const custom = selected === '__custom__' || selected === '';
  $('customVoiceFields').classList.toggle('hidden', selected && selected !== '__custom__');
  $('saveVoiceFields').classList.toggle('hidden', !$('saveVoice').checked);
  $('deleteVoiceBtn').disabled = !selected || selected === '__custom__';
  const voice = state.voices.find((item) => item.name === selected);
  $('voicePreview').classList.toggle('hidden', !voice);
  if (voice) {
    $('voiceAudio').src = voice.audio_url;
    $('voicePromptText').textContent = voice.prompt_text || '无转写';
  } else {
    $('voiceAudio').removeAttribute('src');
    $('voicePromptText').textContent = '';
  }
  if (custom) return;
  $('promptAudio').value = '';
  $('promptText').value = '';
  $('saveVoice').checked = false;
}

function payloadFromForm() {
  const payload = {
    text: $('text').value,
    silence_ms: Number($('silenceMs').value),
    chunk_min_chars: Number($('chunkMinChars').value),
    chunk_max_chars: Number($('chunkMaxChars').value),
    num_steps: Number($('numSteps').value),
    guidance_scale: Number($('guidanceScale').value),
    speaker_scale: Number($('speakerScale').value),
    seed: Number($('seed').value),
    ode_method: $('odeMethod').value,
    template_name: $('templateName').value,
    language: $('language').value || null,
  };
  const voiceName = $('voiceSelect').value;
  if (voiceName && voiceName !== '__custom__') payload.voice_name = voiceName;
  return payload;
}

async function saveVoiceIfNeeded() {
  if (!$('saveVoice').checked) return null;
  const file = $('promptAudio').files[0];
  if (!file) throw new Error('保存音色需要参考音频');
  const form = new FormData();
  form.append('name', $('voiceName').value);
  form.append('prompt_text', $('promptText').value);
  form.append('audio', file);
  const response = await fetch('/api/voices', { method: 'POST', body: form });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(errorMessage(data.detail, '保存音色失败'));
  }
  await loadVoices();
  return response.json();
}

async function submitJob(event) {
  event.preventDefault();
  $('submitBtn').disabled = true;
  $('errorMessage').textContent = '';
  try {
    const voice = await saveVoiceIfNeeded();
    const upload = $('promptAudio').files[0];
    const usesPreset = $('voiceSelect').value && $('voiceSelect').value !== '__custom__';
    let result;
    if (upload && !voice && !usesPreset) {
      const form = new FormData();
      const payload = payloadFromForm();
      for (const [key, value] of Object.entries(payload)) {
        if (value !== null && value !== undefined && key !== 'voice_name') form.append(key, value);
      }
      form.append('prompt_text', $('promptText').value);
      form.append('prompt_audio', upload);
      const response = await fetch('/api/jobs/form', { method: 'POST', body: form });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(errorMessage(data.detail, '提交失败'));
      }
      result = await response.json();
    } else {
      const payload = payloadFromForm();
      if (voice) payload.voice_name = voice.name;
      result = await api('/api/jobs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
    }
    state.currentJobId = result.job_id;
    $('cancelBtn').classList.remove('hidden');
    startPolling();
    await loadHistory();
  } catch (error) {
    $('errorMessage').textContent = error.message;
  } finally {
    $('submitBtn').disabled = false;
  }
}

function renderJob(job) {
  $('statusBadge').textContent = job.status;
  $('statusBadge').className = `status ${job.status}`;
  $('chunkCounter').textContent = `${job.completed_chunks} / ${job.chunk_count}`;
  const percent = job.chunk_count ? Math.round((job.completed_chunks / job.chunk_count) * 100) : 0;
  $('progressBar').value = percent;
  $('errorMessage').textContent = job.error_message || '';

  $('eventLog').replaceChildren(...job.events.map((event) => {
    const li = document.createElement('li');
    li.innerHTML = `<strong>${event.level}</strong> ${new Date(event.created_at).toLocaleTimeString()} · ${event.message}`;
    return li;
  }));

  const done = job.status === 'succeeded';
  $('artifactSection').classList.toggle('hidden', !done);
  if (done) {
    $('finalAudio').src = job.final_wav_url;
    const links = [
      ['final.wav', job.final_wav_url],
      ['final.txt', job.final_text_url],
      ['final.tts', job.final_tts_url],
      ['manifest.json', job.manifest_url],
    ];
    $('downloadLinks').replaceChildren(...links.map(([label, href]) => {
      const a = document.createElement('a');
      a.href = href;
      a.textContent = label;
      a.download = label;
      return a;
    }));
  }
  if (['succeeded', 'failed', 'cancelled'].includes(job.status)) {
    stopPolling();
    $('cancelBtn').classList.add('hidden');
    loadHistory();
  }
}

async function pollJob() {
  if (!state.currentJobId) return;
  try {
    renderJob(await api(`/api/jobs/${state.currentJobId}`));
  } catch (error) {
    $('errorMessage').textContent = error.message;
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  pollJob();
  state.pollTimer = setInterval(pollJob, 1000);
}

function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function cancelCurrentJob() {
  if (!state.currentJobId) return;
  await api(`/api/jobs/${state.currentJobId}/cancel`, { method: 'POST' });
  await pollJob();
}

async function loadHistory() {
  const jobs = await api('/api/jobs');
  $('historyBody').replaceChildren(...jobs.map((job) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${job.id.slice(0, 8)}</code></td>
      <td>${job.status}</td>
      <td>${job.text_preview}</td>
      <td>${job.completed_chunks} / ${job.chunk_count}</td>
      <td>${new Date(job.created_at).toLocaleString()}</td>
      <td class="table-actions">
        <button type="button" class="secondary view-job" data-job-id="${job.id}">查看</button>
        <button type="button" class="danger delete-job" data-job-id="${job.id}">删除</button>
      </td>
    `;
    tr.querySelector('.view-job').addEventListener('click', async () => {
      state.currentJobId = job.id;
      renderJob(await api(`/api/jobs/${job.id}`));
    });
    tr.querySelector('.delete-job').addEventListener('click', async () => deleteJob(job.id));
    return tr;
  }));
}

async function deleteJob(jobId) {
  if (!confirm('确定删除这个任务及其产出物吗？')) return;
  await api(`/api/jobs/${jobId}`, { method: 'DELETE' });
  if (state.currentJobId === jobId) {
    state.currentJobId = null;
    stopPolling();
    $('statusBadge').textContent = '已删除';
    $('statusBadge').className = 'status cancelled';
    $('chunkCounter').textContent = '0 / 0';
    $('progressBar').value = 0;
    $('artifactSection').classList.add('hidden');
    $('eventLog').replaceChildren();
  }
  await loadHistory();
}

async function deleteSelectedVoice() {
  const name = $('voiceSelect').value;
  if (!name || name === '__custom__') return;
  await api(`/api/voices/${name}`, { method: 'DELETE' });
  await loadVoices();
}

async function init() {
  try {
    fillConfig(await api('/api/config'));
    await loadVoices();
    await loadHistory();
  } catch (error) {
    $('errorMessage').textContent = error.message;
  }
}

$('jobForm').addEventListener('submit', submitJob);
$('voiceSelect').addEventListener('change', updateVoiceUI);
$('saveVoice').addEventListener('change', updateVoiceUI);
$('deleteVoiceBtn').addEventListener('click', deleteSelectedVoice);
$('cancelBtn').addEventListener('click', cancelCurrentJob);
$('refreshHistoryBtn').addEventListener('click', loadHistory);
init();
