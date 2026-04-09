/** 
 * AudioEZ - Main Application JavaScript
 */

class AudioEZApp {
    constructor() {
        this.py_channel = null;
        this.equalizerPoints = [];
        this.targetEqualizerPoints = [];
        this.earphonesCurve = [];
        this.autoEqDb = [];
        
        // UI State
        this.isDragging = false;
        this.dragPointIndex = -1;
        this.selectedPointIndex = -1;
        this.selectedheadphone = null;
        this.pendingHeadphoneName = null;
        this.MODEL_NAME_LDFM = null;
        this.TARGET_NAME_LDFM = null;
        
        // Canvas and Graph
        this.canvas = null;
        this.ctx = null;
        this.watermarkImage = new Image();
        
        // Coefficients cache
        this.pointCoefficients = [];
        this.preampLinear = 1.0;
        this.bassCoeffs = null;
        this.trebleCoeffs = null;

        // Simulated curve cache
        this.simulatedCurve = [];
        this.simulatedCurveNeedsUpdate = true;
        
        // Constants
        this.MIN_FREQ = 20;
        this.MAX_FREQ = 20000;
        this.MIN_GAIN = -20;
        this.MAX_GAIN = 20;
        this.LOG_MIN_FREQ = Math.log10(this.MIN_FREQ);
        this.LOG_MAX_FREQ = Math.log10(this.MAX_FREQ);

        this.appSettings = {};

        // Undo/Redo history (max 50 snapshots)
        this._undoStack = [];
        this._redoStack = [];
        this._historyPaused = false;

        // A/B compare
        this._abSlotA = null;   // frozen reference snapshot
        this._abActive = false; // true = currently showing A

        // Debounce timer id for Python calls during drag
        this._pyDebounceTimer = null;

        this.init();
    }

    get priorityTargets() {
        return [
            "AutoEq in-ear",
            "711 5128 delta",
            "Diffuse field 5128 -1dB per octave",
            "Diffuse field 5128",
            "Diffuse field GRAS KEMAR",
            "Diffuse field ISO 11904-1",
            "HMS II.3 AutoEq in-ear",
            "HMS II.3 Harman in-ear 2019 without bass",
            "HMS II.3 Harman over-ear 2018 without bass",
            "Harman in-ear 2016 without bass",
            "Harman in-ear 2016",
            "Harman in-ear 2017-1 without bass",
            "Harman in-ear 2017-1",
            "Harman in-ear 2017-2 without bass",
            "Harman in-ear 2017-2",
            "Harman in-ear 2019 without bass",
            "Harman in-ear 2019",
            "Harman loudspeaker in-room flat 2013",
            "Harman over-ear 2013 without bass",
            "Harman over-ear 2013",
            "Harman over-ear 2015 without bass",
            "Harman over-ear 2015",
            "Harman over-ear 2018 without bass",
            "Harman over-ear 2018",
            "Headphone.com Legacy AutoEq in-ear",
            "Headphone.com Legacy Harman in-ear 2016",
            "Headphone.com Legacy Harman in-ear 2017",
            "Headphone.com Legacy Harman in-ear 2019",
            "Headphone.com Legacy Harman over-ear 2013",
            "Headphone.com Legacy Harman over-ear 2015",
            "Headphone.com Legacy Harman over-ear 2018",
            "Headphone.com Legacy original",
            "Headphone.com Legacy SBAF-Serious",
            "HMS II.3 AutoEq in-ear",
            "HMS II.3 Harman in-ear 2019 without bass",
            "HMS II.3 Harman over-ear 2018 without bass",
            "Innerfidelity 2016",
            "Innerfidelity 2017",
            "Innerfidelity AutoEq in-ear",
            "Innerfidelity Harman in-ear 2019 without bass",
            "Innerfidelity Harman in-ear 2019",
            "Innerfidelity Harman over-ear 2018 without bass",
            "Innerfidelity Harman over-ear 2018",
            "Innerfidelity SBAF Serious",
            "Innerfidelity transformation 2016 to 2017",
            "JM-1 with Harman filters",
            "JM-1 with Harman treble filter",
            "LMG 5128 0.6 without bass",
            "LMG 5128 0.6",
            "oratory1990 in-ear without bass",
            "oratory1990 in-ear",
            "oratory1990 optimum hifi over-ear",
            "Rtings AutoEq in-ear",
            "Rtings Harman in-ear 2019 without bass",
            "Rtings Harman in-ear 2019",
            "Rtings Harman over-ear 2018 without bass",
            "Rtings Harman over-ear 2018",
            "Rtings in-ear original with bass",
            "Rtings orginal average",
            "Rtings original with bass",
            "Rtings original",
            "Rtings SBAF-Serious",
            "Zero"
        ];
    }

    get filterTypeCodes() {
        return {
            'PK': 0, 'LP': 1, 'HP': 2, 'BP': 3, 'LS': 4, 'HS': 5,
            'NO': 6, 'AP': 7, 'LSD': 8, 'HSD': 9, 'BWLP': 10, 'BWHP': 11,
            'LRLP': 12, 'LRHP': 13, 'LSQ': 14, 'HSQ': 15, 'LSC': 16, 'HSC': 17
        };
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            this.initializeElements();
            this.setupCanvas();
            this.setupEventListeners();
            this.setupWebChannel();
            this.watermarkImage.src = 'AudioEZGirl.png';
            this.patchConsoleToPython();
        });
    }

    initializeElements() {
        this.elements = {
            // Canvas and Graph
            canvas: document.getElementById('eq-graph'),
            statusMessage: document.getElementById('status-message'),
            
            // Controls
            preampSlider: document.getElementById('preamp-slider'),
            preampValue: document.getElementById('preamp-value'),
            bassSlider: document.getElementById('bass-slider'),
            bassValue: document.getElementById('bass-value'),
            trebleSlider: document.getElementById('treble-slider'),
            trebleValue: document.getElementById('treble-value'),
            toggleButton: document.getElementById('toggle-button'),
            
            // Configuration
            configStatusLabel: document.getElementById('config-status-label'),
            configListSelect: document.getElementById('config-list-select'),
            saveConfigButton: document.getElementById('save-config-button'),
            exportConfigButton: document.getElementById('export-config-button'),
            exportAllConfigsButton: document.getElementById('export-all-configs-button'),
            importConfigButton: document.getElementById('import-config-button'),
            deleteConfigButton: document.getElementById('delete-config-button'),
            
            // Point Parameters
            eqMessage: document.getElementById('eq-message'),
            pointParametersPanel: document.getElementById('point-parameters'),
            pointGainSlider: document.getElementById('point-gain-slider'),
            pointGainValue: document.getElementById('point-gain-value'),
            pointFreqSlider: document.getElementById('point-freq-slider'),
            pointFreqValue: document.getElementById('point-freq-value'),
            pointQSlider: document.getElementById('point-q-slider'),
            pointQValue: document.getElementById('point-q-value'),
            pointBandsValueInput: document.getElementById('point-bands-value'),
            typeListSelect: document.getElementById('type-list-select'),
            
            // AutoEQ
            toggleAutoEqBtn: document.getElementById('toggle-autoeq'),
            headphoneList: document.getElementById('headphone-list'),
            targetList: document.getElementById('target-list'),
            
            // Export Modal
            exportModal: document.getElementById('export-modal'),
            closeExportModalBtn: document.getElementById('close-export-modal'),
            closeModalFooterBtn: document.getElementById('close-modal-footer-btn'),
            generateExportBtn: document.getElementById('generate-export-btn'),
            profileNameInput: document.getElementById('profile-name-input'),
            exportFormatRadios: document.querySelectorAll('input[name="export-format"]'),
            graphicOptionsDiv: document.getElementById('graphic-options'),
            exportPointBandsValue: document.getElementById('export-point-bands-value'),
            exportTargetBands: document.getElementById('export-target-bands'),
            parametricBandsOption: document.getElementById('parametric-bands-option'),
            platformSelect: document.getElementById('platform-select'),
            warningMessage: document.getElementById('Warning-message'),
            successMessage: document.getElementById('Success-message'),
            
            // Parameters Modal
            parametersModal: document.getElementById('parameters-modal'),
            closeParametersModalBtn: document.getElementById('close-parameters-modal'),
            saveParametersBtn: null, // removed — settings auto-save
            parametersBtn: document.getElementById('parameters-btn'),
            detectEarphoneCheckbox: document.getElementById('detect-earphone'),
            PersistentStateCheckbox: document.getElementById('persistent-state'),
            targetSelect: document.getElementById('target-select'),
            defaultTargetSelect: document.getElementById('default-target-select'),
            readyOnStartupCheckbox: document.getElementById('ready-on-startup'),
            defaultHeadphoneSelect: document.getElementById('default-headphone-select'),
            defaultConfigurationSelect: document.getElementById('default-configuration-select'),
            discordRpcCheckbox: document.getElementById('discord-rpc-checkbox'),
            launchWithWindowsCheckbox: document.getElementById('launch-with-windows'),
            adaptiveFilterState: document.getElementById('adaptive-filter-state'),
            adaptiveStatusRow:        document.getElementById('adaptive-status-row'),
            adaptiveStatusText:       document.getElementById('adaptive-status-text'),
            adaptiveStatusProfile:    document.getElementById('adaptive-status-profile'),
            adaptiveAdvanced:         document.getElementById('adaptive-advanced'),
            adaptiveAdvancedToggle:   document.getElementById('adaptive-advanced-toggle'),
            adaptiveAdvancedBody:     document.getElementById('adaptive-advanced-body'),
            adaptiveSpeechThreshold:  document.getElementById('adaptive-speech-threshold'),
            adaptiveSpeechThresholdVal: document.getElementById('adaptive-speech-threshold-val'),
            adaptiveMusicThreshold:   document.getElementById('adaptive-music-threshold'),
            adaptiveMusicThresholdVal:document.getElementById('adaptive-music-threshold-val'),
            adaptiveHysteresis:       document.getElementById('adaptive-hysteresis'),
            adaptiveHysteresisVal:    document.getElementById('adaptive-hysteresis-val'),
            adaptiveCooldown:         document.getElementById('adaptive-cooldown'),
            adaptiveCooldownVal:      document.getElementById('adaptive-cooldown-val'),
            adaptiveTransition:       document.getElementById('adaptive-transition'),
            adaptiveTransitionVal:    document.getElementById('adaptive-transition-val'),
            adaptiveManualOverride:   document.getElementById('adaptive-manual-override'),
            adaptiveProfileGrid:      document.getElementById('adaptive-profile-grid'),
            
            // Delete Modal
            deleteModalOverlay: document.getElementById('delete-modal-overlay'),
            deleteModalMessage: document.getElementById('delete-modal-message'),
            deleteModalYesBtn: document.getElementById('delete-modal-yes'),
            deleteModalNoBtn: document.getElementById('delete-modal-no'),

            // Credits
            creditaudioez: document.getElementById('credit-audioez'),

            // V1.1
            clipIndicator:              document.getElementById('clip-indicator'),
            newsBtn:                    document.getElementById('news-btn'),
            undoBtn:                    document.getElementById('undo-btn'),
            redoBtn:                    document.getElementById('redo-btn'),
            abBtn:                      document.getElementById('ab-btn'),
            abBtnLabel:                 document.getElementById('ab-btn-label'),
            exportApoIncludeButton:     document.getElementById('export-apo-include-button'),
            exportMoreBtn:              document.getElementById('export-more-btn'),
            exportDropdown:             document.getElementById('export-dropdown'),
            exportPngButton:            document.getElementById('export-png-button'),
            safeModeCb:                 document.getElementById('safe-mode-checkbox'),
            safeModeMaxSlider:          document.getElementById('safe-mode-max-slider'),
            safeModeMaxValue:           document.getElementById('safe-mode-max-value'),
            safeModeMaxLabel:           document.getElementById('safe-mode-max-label'),
            changelogModal:             document.getElementById('changelog-modal'),
            closeChangelogModal:        document.getElementById('close-changelog-modal'),
            closeChangelogOk:           document.getElementById('close-changelog-ok'),
            renameModal:                document.getElementById('rename-modal'),
            renameInput:                document.getElementById('rename-input'),
            renameModalOk:              document.getElementById('rename-modal-ok'),
            renameModalCancel:          document.getElementById('rename-modal-cancel'),
            resetEqBtn:                 document.getElementById('reset-eq-btn'),
            renameConfigBtn:            document.getElementById('rename-config-btn'),
            autoPreampBtn:              document.getElementById('auto-preamp-btn'),
            tagConfigBtn:               document.getElementById('tag-config-btn'),
            tagFilterSelect:            document.getElementById('tag-filter-select'),
            tagModal:                   document.getElementById('tag-modal'),
            tagModalTitle:              document.getElementById('tag-modal-title'),
            tagModalSelect:             document.getElementById('tag-modal-select'),
            tagModalOk:                 document.getElementById('tag-modal-ok'),
            tagModalCancel:             document.getElementById('tag-modal-cancel')
        };

        // Tag state - holds the current preset->tag map and active filter
        this.presetTags = {};
        this.activeTagFilter = "";
        this.allConfigNames = [];

        this.canvas = this.elements.canvas;
        this.ctx = this.canvas?.getContext('2d');
    }

    setupCanvas() {
        if (!this.canvas || !this.ctx) return;
        
        const onResize = () => {
            const devicePixelRatio = window.devicePixelRatio || 1;
            const parentWidth = this.canvas.parentElement.offsetWidth;
            const parentHeight = this.canvas.parentElement.offsetHeight;

            this.canvas.width = parentWidth * devicePixelRatio;
            this.canvas.height = parentHeight * devicePixelRatio;
            this.canvas.style.width = parentWidth + 'px';
            this.canvas.style.height = parentHeight + 'px';

            this.drawGraph();
        };

        window.addEventListener('resize', onResize);
        onResize();
    }

    setupEventListeners() {
        this.setupCanvasEventListeners();
        this.setupControlEventListeners();
        this.setupModalEventListeners();
        this.setupConfigEventListeners();
        this.setupParameterEventListeners();
        this.setupAutoEQEventListeners();
        this.setupExportEventListeners();
        this.setupV11EventListeners();
        this.setupKeyboardShortcuts();

        document.querySelectorAll('input[type="radio"]').forEach(r => {
            r.addEventListener('change', () => {
                r.style.display = 'none';
                r.offsetHeight; // force reflow
                r.style.display = '';
            });
        });

        // Qt WebEngine doesn't always repaint CSS :checked transitions.
        // Use a .checked class on the slider span to force visual update.
        document.querySelectorAll('.switch input[type="checkbox"]').forEach(cb => {
            const slider = cb.nextElementSibling;
            if (!slider) return;
            // Sync initial state
            slider.classList.toggle('checked', cb.checked);
            cb.addEventListener('change', () => {
                slider.classList.toggle('checked', cb.checked);
                // Force repaint
                slider.style.display = 'none';
                slider.offsetHeight;
                slider.style.display = '';
            });
        });
    }

    setupCanvasEventListeners() {
        if (!this.canvas) return;

        this.canvas.addEventListener('mousedown', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            this.dragPointIndex = this.getPointIndex(x, y);

            if (this.dragPointIndex !== -1) {
                if (this.selectedPointIndex === this.dragPointIndex) {
                    this.selectedPointIndex = -1;
                    this.hidePointParameters();
                } else {
                    this._pushHistory();
                    this.isDragging = true;
                    this.canvas.style.cursor = 'move';
                    this.selectedPointIndex = this.dragPointIndex;
                    const point = this.equalizerPoints.find(p => p.index === this.selectedPointIndex);
                    if (point) {
                        this.showPointParameters(point);
                    } else {
                        this.hidePointParameters();
                    }
                }
            } else {
                this.selectedPointIndex = -1;
                this.hidePointParameters();
            }
            this.drawGraph();
        });

        this.canvas.addEventListener('mouseup', () => {
            this.isDragging = false;
            this.canvas.style.cursor = 'default';
            this.drawGraph();
        });

        this.canvas.addEventListener('wheel', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const hoverIndex = this.getPointIndex(x, y);

            const targetIndex = hoverIndex !== -1 ? hoverIndex : this.selectedPointIndex;
            if (targetIndex === -1) return;

            e.preventDefault();
            const point = this.equalizerPoints.find(p => p.index === targetIndex);
            if (!point) return;

            this._pushHistory();
            const step = e.shiftKey ? 0.1 : 0.5;
            const delta = e.deltaY < 0 ? step : -step;
            let newGain = point.gain + delta;
            newGain = Math.min(Math.max(newGain, this.MIN_GAIN), this.MAX_GAIN);
            newGain = parseFloat(newGain.toFixed(1));
            point.gain = newGain;

            if (this.py_channel) {
                this.py_channel.setEqualizerPointParameter(targetIndex, 'gain', newGain);
            }

            if (targetIndex === this.selectedPointIndex) {
                this.elements.pointGainSlider.value = newGain;
                this.elements.pointGainValue.value = newGain;
            }

            this.updateCoefficients();
            this.drawGraph();
        }, { passive: false });

        this.canvas.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const padding = 25;
            const paddedWidth = rect.width - 2 * padding;
            const paddedHeight = rect.height - 2 * padding;

            // --- Tooltip: show freq + gain at cursor position ---
            const tooltip = document.getElementById('graph-tooltip');
            if (tooltip && !this.isDragging) {
                let xNorm = (x - padding) / paddedWidth;
                xNorm = Math.min(Math.max(xNorm, 0), 1);
                const hoverLogFreq = this.LOG_MIN_FREQ + xNorm * (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ);
                const hoverFreq = Math.pow(10, hoverLogFreq);
                const hoverGain = this.getSimulatedGain(hoverFreq);
                const freqLabel = hoverFreq >= 1000 ? `${(hoverFreq / 1000).toFixed(1)} kHz` : `${Math.round(hoverFreq)} Hz`;
                tooltip.textContent = `${freqLabel}  ${hoverGain >= 0 ? '+' : ''}${hoverGain.toFixed(1)} dB`;
                tooltip.style.display = 'block';
                tooltip.style.left = Math.min(x + 12, rect.width - tooltip.offsetWidth - 4) + 'px';
                tooltip.style.top = Math.max(y - 28, 2) + 'px';
            }

            // --- Drag logic ---
            if (!this.isDragging) return;

            const point = this.equalizerPoints.find(p => p.index === this.dragPointIndex);
            if (!point) return;

            let newGain = this.MAX_GAIN - ((y - padding) / paddedHeight) * (this.MAX_GAIN - this.MIN_GAIN);
            newGain = Math.min(Math.max(newGain, this.MIN_GAIN), this.MAX_GAIN);
            newGain = parseFloat(newGain.toFixed(1));

            let xNormDrag = (x - padding) / paddedWidth;
            xNormDrag = Math.min(Math.max(xNormDrag, 0), 1);
            const newLogFreq = this.LOG_MIN_FREQ + xNormDrag * (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ);
            const newFreq = Math.pow(10, newLogFreq);
            const roundedFreq = Math.round(newFreq);

            point.freq = roundedFreq;
            point.gain = newGain;

            this.elements.pointFreqSlider.value = roundedFreq;
            this.elements.pointFreqValue.value = roundedFreq;
            this.elements.pointGainSlider.value = newGain;
            this.elements.pointGainValue.value = newGain;

            if (this.py_channel) {
                this.py_channel.setEqualizerPointParameter(this.dragPointIndex, 'gain', newGain);
                this.py_channel.setEqualizerPointParameter(this.dragPointIndex, 'freq', roundedFreq);
            }

            document.getElementById('band-index').textContent = `Band n°${this.dragPointIndex + 1}`;

            this.updateCoefficients();
            this.drawGraph();
        });

        this.canvas.addEventListener('mouseleave', () => {
            const tooltip = document.getElementById('graph-tooltip');
            if (tooltip) tooltip.style.display = 'none';
        });
    }

    setupControlEventListeners() {
        const { preampSlider, preampValue, bassSlider, bassValue, trebleSlider, trebleValue, toggleButton } = this.elements;

        // Preamp controls
        preampSlider.oninput = (e) => {
            preampValue.value = e.target.value;
            if (this.py_channel) {
                this.py_channel.setPreampGain(parseFloat(e.target.value));
                this._notifyManualEqChange();
            }
            this.updateCoefficients();
            this.drawGraph();
        };

        preampValue.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            preampSlider.value = value;
            if (this.py_channel) {
                this.py_channel.setPreampGain(value);
                this._notifyManualEqChange();
            }
            this.updateCoefficients();
            this.drawGraph();
        });

        // Bass controls
        bassSlider.oninput = (e) => {
            bassValue.value = e.target.value;
            if (this.py_channel) {
                this.py_channel.setBassGain(parseFloat(e.target.value));
                this._notifyManualEqChange();
            }
            this.updateCoefficients();
            this.drawGraph();
        };

        bassValue.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            bassSlider.value = value;
            if (this.py_channel) {
                this.py_channel.setBassGain(value);
                this._notifyManualEqChange();
            }
            this.updateCoefficients();
            this.drawGraph();
        });

        // Treble controls
        trebleSlider.oninput = (e) => {
            trebleValue.value = e.target.value;
            if (this.py_channel) {
                this.py_channel.setTrebleGain(parseFloat(e.target.value));
                this._notifyManualEqChange();
            }
            this.updateCoefficients();
            this.drawGraph();
        };

        trebleValue.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            trebleSlider.value = value;
            if (this.py_channel) {
                this.py_channel.setTrebleGain(value);
                this._notifyManualEqChange();
            }
            this.updateCoefficients();
            this.drawGraph();
        });

        // Toggle button
        toggleButton.onclick = () => {
            if (!this.py_channel) return;
            if (toggleButton.textContent === 'Start') {
                this.py_channel.startPlayback();
            } else {
                this.py_channel.stopPlayback();
            }
        };
    }

    setupModalEventListeners() {
        const { parametersBtn, parametersModal, closeParametersModalBtn } = this.elements;

        if (parametersBtn) {
            parametersBtn.addEventListener('click', () => {
                parametersModal.classList.add('show');
            });
        }

        if (closeParametersModalBtn) {
            closeParametersModalBtn.addEventListener('click', () => {
                parametersModal.classList.remove('show');
            });
        }

        // Map each input id → appSettings key + value reader
        const settingMap = [
            { id: 'ready-on-startup',          key: 'auto_launch',          read: el => el.checked },
            { id: 'detect-earphone',            key: 'detect_earphone',      read: el => el.checked },
            { id: 'persistent-state',           key: 'persistent_state',     read: el => el.checked },
            { id: 'discord-rpc-checkbox',       key: 'discord_rpc',          read: el => el.checked },
            { id: 'launch-with-windows',        key: 'launch_with_windows',  read: el => el.checked },
            { id: 'adaptive-filter-state',      key: 'adaptive_filter',      read: el => el.checked },
            { id: 'safe-mode-checkbox',         key: 'safe_mode',            read: el => el.checked },
            { id: 'safe-mode-max-slider',       key: 'safe_mode_max_db',     read: el => parseFloat(el.value) },
            { id: 'safe-mode-max-value',        key: 'safe_mode_max_db',     read: el => parseFloat(el.value) },
            { id: 'default-target-select',      key: 'default_target',       read: el => el.value },
            { id: 'default-headphone-select',   key: 'default_headphone',    read: el => el.value },
            { id: 'default-configuration-select', key: 'default_configuration', read: el => el.value },
        ];

        settingMap.forEach(({ id, key, read }) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('change', () => {
                // 1. Update appSettings immediately — prevents round-trip from reverting
                if (this.appSettings) this.appSettings[key] = read(el);
                // 2. Persist to Python + show feedback
                setTimeout(() => {
                    this.saveSettingsToPython();
                    this.showToast('Settings saved.', 'success', 1500);
                }, 50);
            });
        });
    }

    setupConfigEventListeners() {
        const { configListSelect, saveConfigButton, exportAllConfigsButton, importConfigButton, deleteConfigButton } = this.elements;

        configListSelect.onchange = (e) => {
            if (this.py_channel) this.py_channel.loadConfig(e.target.value);
        };

        saveConfigButton.onclick = () => {
            const activeConfigName = configListSelect.value;
            let configName = prompt("Configuration name...", activeConfigName);

            configName = configName.trim();
            if (configName) {
                if (configName.toLowerCase() === 'default') {
                    this.showSimpleModal("Cannot overwrite the reserved configuration 'Default'. Please choose another name.");
                    return; 
                }

                const configExists = Array.from(configListSelect.options).some(
                    option => option.value === configName
                );
                                        
                if (configExists) {
                    // use window.confirm()
                    //shouldSave = confirm(`Configuration '${configName}' already exists. Do you want to overwrite it?`);
                    this.showDeleteConfirmModal(`Configuration '${configName}' already exists. Do you want to overwrite it?`, () => {
                        if (this.py_channel) {
                            this.py_channel.saveConfig(configName);
                        }
                    });
                } else {
                    if (this.py_channel) {
                        this.py_channel.saveConfig(configName);
                    }
                }
            }
        };

        exportAllConfigsButton.onclick = () => {
            if (this.elements.exportDropdown) this.elements.exportDropdown.classList.remove('open');
            if (this.py_channel) this.py_channel.exportAllConfigs();
        };
        
        importConfigButton.onclick = () => {
            if (this.py_channel) this.py_channel.importConfig();
        };

        deleteConfigButton.addEventListener('click', () => {
            const selectedConfigName = configListSelect.value;
            const selectedConfigText = configListSelect.options[configListSelect.selectedIndex].text;

            if (!selectedConfigName || selectedConfigName === "" || selectedConfigName === "Default") {
                this.showSimpleModal("You can't delete the default configuration.");
                return;
            }

            this.showDeleteConfirmModal(`Are you sure you want to delete the configuration '${selectedConfigText}'?`, () => {
                if (this.py_channel) {
                    this.py_channel.deleteConfig(selectedConfigName);
                }
            });
        });
    }

    setupParameterEventListeners() {
        const { parametersBtn, parametersModal, closeParametersModalBtn, pointBandsValueInput, pointGainSlider, pointGainValue, pointFreqSlider, pointFreqValue, pointQSlider, pointQValue, typeListSelect } = this.elements;

        pointBandsValueInput.addEventListener('change', (event) => {
            let newCount = parseInt(event.target.value);
            if (newCount > 0 && newCount <= 31) {
                this.updateEqualizerBands(newCount);
            }
            this.drawGraph();
        });

        // Gain controls
        pointGainSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            pointGainValue.value = value;
            this.updatePointParameter('gain', value);
        });

        pointGainValue.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            pointGainSlider.value = value;
            this.updatePointParameter('gain', value);
        });

        // Frequency controls
        pointFreqSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            pointFreqValue.value = value;
            this.updatePointParameter('freq', value);
        });

        pointFreqValue.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            pointFreqSlider.value = value;
            this.updatePointParameter('freq', value);
        });

        // Q controls
        pointQSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            pointQValue.value = value;
            this.updatePointParameter('q', value);
        });

        pointQValue.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            pointQSlider.value = value;
            this.updatePointParameter('q', value);
        });

        // Filter type
        typeListSelect.addEventListener('change', (e) => {
            const value = e.target.value;
            if (this.py_channel && this.selectedPointIndex !== -1) {
                const point = this.equalizerPoints.find(p => p.index === this.selectedPointIndex);
                if (point) {
                    point.type = value;
                    const code = this.filterTypeCodes[value] ?? 0;
                    this.py_channel.setEqualizerPointParameter(this.selectedPointIndex, 'type', code);
                    this.drawGraph();
                }
            }
        });

        if (closeParametersModalBtn) {
            closeParametersModalBtn.addEventListener('click', () => {
                parametersModal.classList.remove('show');
            });
        }
    }

    loadSettingsFromPython() {
        console.log("Loading settings from Python...");
        if (!this.py_channel) {
            console.error("Python channel is not ready.");
            return;
        }

        this.py_channel.getSettings().then((settings_json) => {
            try {
                const settings = JSON.parse(settings_json);
                console.log("Settings received:", settings);
                this.appSettings = settings;
                
                if (this.elements.readyOnStartupCheckbox) {
                    this.elements.readyOnStartupCheckbox.checked = settings.auto_launch;
                }
                if (this.elements.detectEarphoneCheckbox) {
                    this.elements.detectEarphoneCheckbox.checked = settings.detect_earphone;
                }
                if (this.elements.PersistentStateCheckbox) {
                    this.elements.PersistentStateCheckbox.checked = settings.persistent_state;
                }
                if (this.elements.discordRpcCheckbox) {
                    this.elements.discordRpcCheckbox.checked = settings.discord_rpc;
                }
                if (this.elements.launchWithWindowsCheckbox) {
                    this.elements.launchWithWindowsCheckbox.checked = settings.launch_with_windows;
                }
                
                this.py_channel.getAutoEQModelsForSettings().then((models_json) => {
                    const models = JSON.parse(models_json);
                    this.populateDropdown('default-headphone-select', models, settings.default_headphone);
                });

                this.py_channel.getConfigNamesForSettings().then((config_names) => {
                    this.populateDropdown('default-configuration-select', config_names, settings.default_configuration);
                });

                this.populateDropdown('default-target-select', this.priorityTargets, settings.default_target);
                
                this.applyDefaultSelections();
                this.py_channel.fetchCurve(settings.default_target);
                
            } catch (e) {
                console.error("Failed to parse settings JSON:", e);
            }
        });
    }

    saveSettingsToPython() {
        if (!this.py_channel) return;

        const settings = {
            auto_launch:            this.elements.readyOnStartupCheckbox?.checked   ?? false,
            detect_earphone:        this.elements.detectEarphoneCheckbox?.checked   ?? false,
            persistent_state:       this.elements.PersistentStateCheckbox?.checked  ?? false,
            discord_rpc:            this.elements.discordRpcCheckbox?.checked       ?? false,
            launch_with_windows:    this.elements.launchWithWindowsCheckbox?.checked ?? false,
            adaptive_filter:        this.elements.adaptiveFilterState?.checked      ?? false,
            adaptive_config:        this._collectAdaptiveConfigFromUi(),
            default_target:         this.elements.defaultTargetSelect?.value        ?? '',
            default_headphone:      this.elements.defaultHeadphoneSelect?.value     ?? '',
            default_configuration:  this.elements.defaultConfigurationSelect?.value ?? 'Default',
            safe_mode:              this.elements.safeModeCb?.checked               ?? false,
            safe_mode_max_db:       parseFloat(this.elements.safeModeMaxSlider?.value ?? 12)
        };

        this.py_channel.saveSettings(JSON.stringify(settings));

        // Hot-push the adaptive config to RTGD without needing a restart.
        if (this.py_channel.setAdaptiveConfig) {
            try { this.py_channel.setAdaptiveConfig(JSON.stringify(settings.adaptive_config)); }
            catch (e) { /* not available */ }
        }
    }

    populateDropdown(id, items, selectedValue = null) {
        const selectElement = document.getElementById(id);
        if (!selectElement) {
            console.warn(`Element #${id} not found`);
            return;
        }

        selectElement.innerHTML = '';
        items.forEach(item => {
            const option = document.createElement('option');
            option.value = item;
            option.textContent = item;
            if (selectedValue === item) {
                option.selected = true;
            }
            selectElement.appendChild(option);
        });
    }

    setupAutoEQEventListeners() {
        const { toggleAutoEqBtn, headphoneList, targetList, creditaudioez, targetSelect } = this.elements;

        headphoneList.addEventListener('change', () => {
            const selectedValue = headphoneList.value;

            if (selectedValue === "None") {
                this.selectedheadphone = null;
                return;
            }

            this.selectedheadphone = this.autoEqDb.find(e => e.name === selectedValue);

            if (this.py_channel && typeof this.py_channel.fetchCurve === 'function') {
                this.py_channel.fetchCurve(this.selectedheadphone.name);
            }
            this.simulatedCurveNeedsUpdate = true;
            this.drawGraph();
        });

        targetList.addEventListener('change', () => {
            const selectedValue = targetList.value;

            this.selectedtarget = this.autoEqDb.find(e => e.name === selectedValue);

            if (!this.selectedtarget) {
                this.selectedtarget = { name: selectedValue };
            }

            if (this.py_channel && typeof this.py_channel.fetchCurve === 'function') {
                this.py_channel.fetchCurve(this.selectedtarget.name);
            }

            this.simulatedCurveNeedsUpdate = true;
            this.drawGraph();
        });

        toggleAutoEqBtn.addEventListener('click', () => {
            if (!this.selectedheadphone || !this.selectedtarget) return;

            if (this.py_channel && typeof this.py_channel.applyAutoEQProfile === 'function') {
                this.py_channel.applyAutoEQProfile(
                    this.selectedheadphone.name, 
                    this.selectedtarget.name, 
                    this.elements.pointBandsValueInput.value
                );
            }
        });

        creditaudioez.addEventListener('click', () => {
            if (this.py_channel) {
                this.py_channel.openKoFi();
            }
        });
    }

    setupExportEventListeners() {
        const { 
            exportConfigButton, closeExportModalBtn, closeModalFooterBtn, 
            generateExportBtn, exportFormatRadios,
            exportMoreBtn, exportDropdown, exportPngButton
        } = this.elements;

        exportFormatRadios.forEach(radio => {
            radio.addEventListener('change', () => this.toggleGraphicOptions());
        });

        if (exportConfigButton) exportConfigButton.addEventListener('click', () => this.showExportModal());
        if (closeExportModalBtn) closeExportModalBtn.addEventListener('click', () => this.hideExportModal());
        if (closeModalFooterBtn) closeModalFooterBtn.addEventListener('click', () => this.hideExportModal());
        if (generateExportBtn) generateExportBtn.addEventListener('click', () => this.generateExport());

        // Export dropdown toggle — uses fixed positioning to escape overflow:hidden parents
        if (exportMoreBtn && exportDropdown) {
            exportMoreBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = exportDropdown.classList.contains('open');
                exportDropdown.classList.remove('open');
                if (!isOpen) {
                    const rect = exportMoreBtn.getBoundingClientRect();
                    // Open above the button
                    exportDropdown.style.right = (window.innerWidth - rect.right) + 'px';
                    exportDropdown.style.bottom = (window.innerHeight - rect.top + 6) + 'px';
                    exportDropdown.style.left = 'auto';
                    exportDropdown.style.top = 'auto';
                    exportDropdown.classList.add('open');
                }
            });
            document.addEventListener('click', (e) => {
                if (!exportDropdown.contains(e.target) && e.target !== exportMoreBtn) {
                    exportDropdown.classList.remove('open');
                }
            });
        }

        // PNG export
        if (exportPngButton) {
            exportPngButton.addEventListener('click', () => {
                if (exportDropdown) exportDropdown.classList.remove('open');
                this.exportGraphAsPng();
            });
        }
    }

    setupWebChannel() {
        const connectToQt = () => {
            new QWebChannel(qt.webChannelTransport, (channel) => {
                this.py_channel = channel.objects.py_channel;

                if (this.py_channel) {
                    this.setupPythonSignals();
                    console.log("QWebChannel connected and ready.");

                    setTimeout(() => {
                        if (this.py_channel && typeof this.py_channel.requestAutoEQModels === 'function') {
                            this.py_channel.requestAutoEQModels();
                        }
                    }, 100);
                }
            });
        };

        if (typeof qt !== 'undefined' && qt.webChannelTransport) {
            connectToQt();
        } else {
            console.warn("QWebChannel not available yet, retrying...");
            setTimeout(() => this.setupWebChannel(), 50);
        }
    }

    setupPythonSignals() {
        if (!this.py_channel) return;

        const adaptiveFilterSwitch = document.getElementById('adaptive-filter-state');
        if (adaptiveFilterSwitch) {
            adaptiveFilterSwitch.addEventListener('change', (event) => {
                if (this.py_channel) {
                    this.py_channel.toggleAdaptiveFilter(event.target.checked);
                }
                this._updateAdaptiveUiVisibility(event.target.checked);
            });
        }

        // Wire all adaptive advanced controls (idempotent — only attach once).
        this._setupAdaptiveAdvancedControls();

        // Live status from RTGD.
        if (this.py_channel.adaptiveStatusUpdate) {
            this.py_channel.adaptiveStatusUpdate.connect((statusJson) => {
                try {
                    const status = JSON.parse(statusJson);
                    this._renderAdaptiveStatus(status);
                } catch (e) { /* swallow malformed */ }
            });
        }

        this.py_channel.headphoneDetected.connect(headphoneName => {
            console.log(`[JS] Detection signal received: ${headphoneName}`);
            this.pendingHeadphoneName = headphoneName;
        });

        this.py_channel.modelsUpdated.connect((models) => {
            this.autoEqDb = models.map(name => ({ name }));
            this.loadSettingsFromPython();
            
            this.populateList(this.autoEqDb, this.elements.headphoneList);
            this.populateList(this.autoEqDb, this.elements.targetList);
            this.applyDefaultSelections();
        });

        this.py_channel.EarphonesCurve.connect((freqs, rawGains) => {
            console.log("Earphone curve received.");
            this.earphonesCurve = freqs.map((f, i) => ({ freq: f, gain: rawGains[i] }));
            this.drawGraph();
        });

        this.py_channel.targetCurveUpdate.connect((freqs, gains) => {
            console.log("Target curve received:", freqs.length, "points");
            this.targetEqualizerPoints = freqs.map((f, i) => ({ freq: f, gain: gains[i] }));
            this.drawGraph();
        });

        this.py_channel.statusUpdate.connect(status => {
            this.showToast(status, 'info');
            const config = this.elements.configListSelect.options[this.elements.configListSelect.selectedIndex]?.text || 'Default';
            const hp = this.pendingHeadphoneName || this.appSettings?.default_headphone || '';
            const details = hp && hp !== 'None' ? `${hp}` : `Config: ${config}`;
            if (this.py_channel) this.py_channel.update_presence_discord(status, details);
        });

        this.py_channel.frequencyResponseUpdate.connect((freqs, bands, gains, qValues, filterTypes) => {
            console.log("📡 Received frequency response update.");

            this.equalizerPoints = bands.map((freq, i) => ({
                index: i,
                freq: freq,
                gain: gains[i],
                q: qValues[i],
                type: typeof filterTypes?.[i] === 'string' ? filterTypes[i] : 'PK'
            }));

            this.updateTypeSelectOptions();

            const point = this.equalizerPoints.find(p => p.index === this.selectedPointIndex);
            if (point) {
                this.showPointParameters(point);
            } else {
                this.hidePointParameters();
            }

            this.updateCoefficients();
            this.drawGraph();
        });

        this.py_channel.preampGainChanged.connect(gain => {
            this.elements.preampSlider.value = gain;
            this.elements.preampValue.value = gain;
            this.updateCoefficients();
            this.drawGraph();
        });

        this.py_channel.bassGainChanged.connect(gain => {
            this.elements.bassSlider.value = gain;
            this.elements.bassValue.value = gain;
            this.updateCoefficients();
            this.drawGraph();
        });

        this.py_channel.trebleGainChanged.connect(gain => {
            this.elements.trebleSlider.value = gain;
            this.elements.trebleValue.value = gain;
            this.updateCoefficients();
            this.drawGraph();
        });

        this.py_channel.playbackStateChanged.connect(isPlaying => {
            this.elements.toggleButton.textContent = isPlaying ? 'Stop' : 'Start';
            this.elements.toggleButton.className = isPlaying ? 'btn btn-danger' : 'btn btn-primary';
            this.showToast(isPlaying ? 'Equalizer active.' : 'Equalizer disabled.', isPlaying ? 'success' : 'info', 2000);
            if (this.py_channel) {
                const hp = this.pendingHeadphoneName || this.appSettings?.default_headphone || '';
                const bands = this.equalizerPoints.length;
                const state = isPlaying ? '🎧 EQ Active' : '⏸ EQ Disabled';
                const details = hp && hp !== 'None' ? `${hp} · ${bands} bands` : `${bands} bands`;
                this.py_channel.update_presence_discord(state, details);
            }
        });

        this.py_channel.configListUpdate.connect((configList, activeConfig) => {
            this.allConfigNames = configList.slice();
            // Pull tags from python so the UI is always in sync
            try {
                this.py_channel.getPresetTags && this.py_channel.getPresetTags(json => {
                    try { this.presetTags = JSON.parse(json) || {}; }
                    catch (e) { this.presetTags = {}; }
                    this._renderConfigList(activeConfig);
                });
            } catch (e) {
                this._renderConfigList(activeConfig);
            }
            if (this.py_channel) {
                const hp = this.pendingHeadphoneName || this.appSettings?.default_headphone || '';
                const state = hp && hp !== 'None' ? `🎧 ${hp}` : '🎧 AudioEZ';
                this.py_channel.update_presence_discord(state, `Preset: ${activeConfig}`);
            }
        });

        this.py_channel.settingsUpdated.connect((settingsJson) => {
            console.log("Settings updated signal received with data.");
            try {
                const settings = JSON.parse(settingsJson);
                try {
                    this.updateSettings(settings);
                } catch (e) {
                    console.error("Error in updateSettings:", e);
                }
            } catch (e) {
                console.error("Error parsing settings from signal:", e);
            }
        });
    }

    applyDefaultSelections() {
        if (!this.appSettings) return;
        
        console.log("Applying default selections:", this.appSettings);

        if (this.appSettings.default_headphone && this.elements.headphoneList) {
            const headphoneList = this.elements.headphoneList;
            const defaultHeadphone = this.appSettings.default_headphone;
            
            let optionExists = false;
            for (let i = 0; i < headphoneList.options.length; i++) {
                if (headphoneList.options[i].value === defaultHeadphone) {
                    optionExists = true;
                    break;
                }
            }
            
            if (optionExists) {
                headphoneList.value = defaultHeadphone;
                this.selectedheadphone = this.autoEqDb.find(
                    e => e.name === defaultHeadphone
                );
                
                if (this.py_channel) {
                    this.py_channel.fetchCurve(defaultHeadphone);
                }
            } else {
                console.warn(`Default headphone not found: ${defaultHeadphone}`);
            }
        }

        if (this.appSettings.default_target && this.elements.targetList) {
            const targetList = this.elements.targetList;
            const defaultTarget = this.appSettings.default_target;
            
            let optionExists = false;
            for (let i = 0; i < targetList.options.length; i++) {
                if (targetList.options[i].value === defaultTarget) {
                    optionExists = true;
                    break;
                }
            }

            if (optionExists) {
                targetList.value = defaultTarget;

                let targetData = this.autoEqDb.find(e => e.name === defaultTarget);
                if (!targetData) {
                    targetData = { name: defaultTarget };
                }

                this.selectedtarget = targetData;

                if (this.py_channel) {
                    this.py_channel.fetchCurve(defaultTarget);
                }
            } else {
                console.warn(`Default target not found: ${defaultTarget}`);
            }
        }

        if (this.appSettings.default_configuration && this.elements.configListSelect) {
            const configList = this.elements.configListSelect;
            const defaultConfig = this.appSettings.default_configuration;
            
            let optionExists = false;
            for (let i = 0; i < configList.options.length; i++) {
                if (configList.options[i].value === defaultConfig) {
                    optionExists = true;
                    break;
                }
            }
            
            if (optionExists) {
                configList.value = defaultConfig;
                if (this.py_channel) {
                    this.py_channel.loadConfig(defaultConfig);
                }
            }
        }
        
        if (this.appSettings.auto_launch && this.elements.toggleButton) {
            setTimeout(() => {
                if (this.py_channel && !this.isPlaying) {
                    this.py_channel.startPlayback();
                    this.elements.toggleButton.textContent = 'Stop';
                    this.elements.toggleButton.className = 'btn btn-danger';
                }
            }, 25);
        }
    }

    _renderConfigList(activeConfig) {
        const select = this.elements.configListSelect;
        if (!select) return;
        const filter = this.activeTagFilter || "";
        select.innerHTML = '';
        const names = this.allConfigNames || [];
        names.forEach(name => {
            // Always show "Default", and apply tag filter to the rest
            if (filter && name !== "Default") {
                const tag = this.presetTags?.[name] || "";
                if (tag !== filter) return;
            }
            const option = document.createElement('option');
            option.value = name;
            const tag = this.presetTags?.[name];
            option.textContent = tag ? `${name}  [${tag}]` : name;
            if (name === activeConfig) option.selected = true;
            select.appendChild(option);
        });
        // If active wasn't in the filtered set, fall back to first option
        if (!select.value && select.options.length > 0) {
            select.selectedIndex = 0;
        }
    }

    updatePointParameter(param, value) {
        if (this.selectedPointIndex === -1) return;
        const point = this.equalizerPoints.find(p => p.index === this.selectedPointIndex);
        if (!point) return;

        this._pushHistory();
        point[param] = value;

        if (this.py_channel) {
            this.py_channel.setEqualizerPointParameter(this.selectedPointIndex, param, value);
            this._notifyManualEqChange();
        }

        this.updateCoefficients();
        this.drawGraph();
    }

    _notifyManualEqChange() {
        // Throttled ping to RTGD so it pauses adaptive switches when the user touches the EQ.
        if (!this.py_channel || !this.py_channel.notifyManualEqChange) return;
        const now = Date.now();
        if (this._lastManualOverrideNotify && (now - this._lastManualOverrideNotify) < 500) return;
        this._lastManualOverrideNotify = now;
        try { this.py_channel.notifyManualEqChange(); } catch (e) { /* ignore */ }
    }

    updateEqualizerBands(newBandCount) {
        const currentBandCount = this.equalizerPoints.length;

        if (newBandCount > currentBandCount) {
            for (let i = currentBandCount; i < newBandCount; i++) {
                const logStep = (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) / (newBandCount - 1);
                const freq = Math.pow(10, this.LOG_MIN_FREQ + i * logStep);
                
                this.equalizerPoints.push({
                    index: i,
                    freq: Math.round(freq),
                    gain: 0,
                    q: 1.414,
                    type: 'PK'
                });
            }
        } else if (newBandCount < currentBandCount) {
            this.equalizerPoints.length = newBandCount;
        }
        
        if (this.elements.pointBandsValueInput) {
            this.elements.pointBandsValueInput.value = this.equalizerPoints.length;
        }

        // Sync band count to Python engine
        if (this.py_channel) this.py_channel.resizeBands(this.equalizerPoints.length);

        this.updateCoefficients();
        this.drawGraph();
    }

    updateTypeSelectOptions() {
        const select = this.elements.typeListSelect;
        const filterTypes = ['PK', 'LP', 'HP', 'BP', 'LS', 'HS', 'NO', 'AP', 'LSD', 'HSD', 'BWLP', 'BWHP', 'LRLP', 'LRHP', 'LSQ', 'HSQ', 'LSC', 'HSC'];
        const filterNameTypes = [
            'Peaking', 'Low-pass', 'High-pass', 'Band-pass', 'Low-shelf', 'High-shelf', 
            'Notch', 'All-pass', 'Low-shelf (dB Slope)', 'High-shelf (dB Slope)', 
            'Butterworth Low-pass (even orders only)', 'Butterworth High-pass (even orders only)', 
            'Linkwitz-Riley Low-pass (even orders only)', 'Linkwitz-Riley High-pass (even orders only)', 
            'Low-shelf (Q as slope)', 'High-shelf (Q as slope)', 
            'Low-shelf (corner frequency, Q as slope)', 'High-shelf (corner frequency, Q as slope)'
        ];
        
        select.innerHTML = '';

        filterTypes.forEach(type => {
            const option = document.createElement('option');
            option.value = type;
            option.textContent = `(${type}) ${filterNameTypes[filterTypes.indexOf(type)]}`;
            select.appendChild(option);
        });

        const point = this.equalizerPoints.find(p => p.index === this.selectedPointIndex);
        if (point && point.type) {
            select.value = point.type;
        }
    }

    getPointIndex(x, y) {
        if (this.equalizerPoints.length === 0) return -1;
        const rect = this.canvas.getBoundingClientRect();
        const width = this.canvas.width / (window.devicePixelRatio || 1);
        const height = this.canvas.height / (window.devicePixelRatio || 1);

        const ratioX = width / rect.width;
        const ratioY = height / rect.height;
        const actualX = x * ratioX;
        const actualY = y * ratioY;

        const padding = 25;
        const paddedWidth = width - 2 * padding;
        const paddedHeight = height - 2 * padding;
        
        for (let i = 0; i < this.equalizerPoints.length; i++) {
            const logFreq = Math.log10(this.equalizerPoints[i].freq);
            const pointX = padding + (logFreq - this.LOG_MIN_FREQ) / (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) * paddedWidth;
            const pointY = padding + paddedHeight * (1 - (this.equalizerPoints[i].gain - this.MIN_GAIN) / (this.MAX_GAIN - this.MIN_GAIN));
            const dist = Math.sqrt(Math.pow(actualX - pointX, 2) + Math.pow(actualY - pointY, 2));
            if (dist < 15) return this.equalizerPoints[i].index;
        }
        return -1;
    }

    showPointParameters(point) {
        if (!point || typeof point.gain !== 'number' || typeof point.freq !== 'number' || typeof point.q !== 'number') {
            this.hidePointParameters();
            return;
        }
        this.elements.eqMessage.classList.add('hide-rem');
        this.elements.pointParametersPanel.classList.remove('hide');

        document.getElementById('band-index').textContent = `Band n°${point.index + 1}`;

        this.elements.pointGainSlider.value = point.gain;
        this.elements.pointGainValue.value = point.gain;
        this.elements.pointFreqSlider.value = point.freq;
        this.elements.pointFreqValue.value = point.freq;
        this.elements.pointQSlider.value = point.q;
        this.elements.pointQValue.value = point.q;

        const typeSelect = this.elements.typeListSelect;
        if (point.type) {
            typeSelect.value = point.type;
        } else {
            typeSelect.value = 'PK';
        }
    }

    hidePointParameters() {
        this.elements.eqMessage.classList.remove('hide-rem');
        this.elements.pointParametersPanel.classList.add('hide');
    }

    populateList(list, element) {
        element.innerHTML = "";
        const seenDisplayNames = new Set();

        if (element.id === 'target-list') {
            this.priorityTargets.forEach(name => {
                if (!seenDisplayNames.has(name)) {
                    seenDisplayNames.add(name);
                    const option = document.createElement("option");
                    option.value = name;
                    option.textContent = name;
                    element.appendChild(option);
                }
            });
        } 
        else {
            const noneOption = document.createElement("option");
            noneOption.value = "None";
            noneOption.textContent = "None";
            element.appendChild(noneOption);
        }

        list.forEach(item => {
            const displayName = item.name.split("/").pop();
            if (seenDisplayNames.has(displayName)) return;
            seenDisplayNames.add(displayName);

            const option = document.createElement("option");
            option.value = item.name;
            option.textContent = displayName;
            
            if (element.id === this.elements.headphoneList.id) {
                const lowerDisplayName = displayName.toLowerCase();
                const lowerPendingHeadphoneName = this.pendingHeadphoneName ? this.pendingHeadphoneName.toLowerCase() : null;
                
                if (lowerPendingHeadphoneName && lowerDisplayName === lowerPendingHeadphoneName) {
                    option.selected = true;
                    this.selectedheadphone = item;
                    if (this.py_channel) {
                        this.py_channel.fetchCurve(item.name);
                    }
                }
            }

            element.appendChild(option);
        });
    }

    populateSettingsSelects() {

        this.autoEqDb.forEach(item => {
            const option = document.createElement('option');
            option.value = item.name;
            option.textContent = item.name.split("/").pop();
            this.elements.defaultHeadphoneSelect.appendChild(option);
        });
        
        this.elements.configListSelect.querySelectorAll('option').forEach(option => {
            if (option.value !== "Default") {
                const clone = option.cloneNode(true);
                this.elements.defaultConfigurationSelect.appendChild(clone);
            }
        });

        this.priorityTargets.forEach(target => {
            const option = document.createElement('option');
            option.value = target;
            option.textContent = target;
            this.elements.defaultTargetSelect.appendChild(option);
        });
    }

    toggleGraphicOptions() {
        const selectedFormat = document.querySelector('input[name="export-format"]:checked').value;
        if (selectedFormat === 'graphic') {
            this.elements.graphicOptionsDiv.style.display = 'block';
        } else {
            this.elements.graphicOptionsDiv.style.display = 'none';
        }
    }

    exportGraphAsPng() {
        if (!this.canvas) return;
        try {
            // Draw on a white-background copy so the PNG is readable on light backgrounds
            const offscreen = document.createElement('canvas');
            offscreen.width  = this.canvas.width;
            offscreen.height = this.canvas.height;
            const octx = offscreen.getContext('2d');
            octx.fillStyle = '#0d121c';
            octx.fillRect(0, 0, offscreen.width, offscreen.height);
            octx.drawImage(this.canvas, 0, 0);

            const link = document.createElement('a');
            const configName = this.elements.configListSelect?.value || 'AudioEZ';
            link.download = `${configName}_EQ.png`;
            link.href = offscreen.toDataURL('image/png');
            link.click();
            this.showToast('Graph saved as PNG.', 'success', 2000);
        } catch (e) {
            this.showToast('PNG export failed.', 'error', 3000);
            console.error('[PNG Export]', e);
        }
    }

    showExportModal() {
        this.elements.exportModal.style.visibility = 'visible';
        this.elements.exportModal.style.opacity = '1';

        this.elements.profileNameInput.value = (this.selectedheadphone && this.selectedtarget) ?
            `${this.selectedheadphone.name} - ${this.selectedtarget.name}` :
            'New configuration';

        // Default export band count to 0 (= keep current)
        if (this.elements.exportTargetBands) {
            this.elements.exportTargetBands.value = 0;
        }

        this.toggleGraphicOptions();
        this.elements.warningMessage.style.display = 'none';
        this.elements.successMessage.style.display = 'none';
    }

    hideExportModal() {
        this.elements.warningMessage.style.display = 'none';
        this.elements.successMessage.style.display = 'none';
        this.elements.exportModal.style.visibility = 'hidden';
        this.elements.exportModal.style.opacity = '0';
        this.elements.warningMessage.querySelector('label').textContent = "⚠ Warning: x";
        this.elements.successMessage.querySelector('label').textContent = "✅ Success: x";
    }

    
    generateExport() {
        this.elements.warningMessage.style.display = 'none';
        this.elements.successMessage.style.display = 'none';

        const profileName = this.elements.profileNameInput.value.trim();
        if (!profileName) {
            this.elements.warningMessage.querySelector('label').textContent = "⚠ Warning: Profile name cannot be empty.";
            this.elements.warningMessage.style.display = 'block';
            return;
        }

        const exportFormat = document.querySelector('input[name="export-format"]:checked');
        
        if (!exportFormat) {
            this.elements.warningMessage.querySelector('label').textContent = "⚠ Warning: Please select an export format.";
            this.elements.warningMessage.style.display = 'block';
            return;
        }

        const platformSelect = this.elements.platformSelect;
        
        const formatValue = platformSelect.value;
        
        let extension = '';
        console.log("Selected export format:", formatValue);
        switch (formatValue) {
            case 'audioez':
                extension = '.aez';
                break;
            case 'equalizerapo':
                extension = '.txt';
                break;
            case 'peace':
                extension = '.peace';
                break;
            case 'wavelet':
                extension = '.json';
                break;
            case 'wavelet2':
                extension = '.wavelet';
                break;
            default:
                this.elements.warningMessage.querySelector('label').textContent = "⚠ Warning: Invalid export format selected.";
                this.elements.warningMessage.style.display = 'block';
                return;
        }

        const targetBands = parseInt(this.elements.exportTargetBands?.value) || 0;

        const exportData = {
            suggestedFileName: profileName + extension,
            exportType: formatValue,
            targetBands: targetBands
        };

        if (this.py_channel && this.py_channel.exportConfig) {
            this.py_channel.exportConfig(JSON.stringify(exportData));
            
            this.elements.successMessage.querySelector('label').textContent = `✅ Success: Configuration exported as ${extension}.`;
            this.elements.successMessage.style.display = 'block';
            setTimeout(() => {
                this.hideExportModal();
            }, 1500);
            
        } else {
            this.elements.warningMessage.querySelector('label').textContent = "⚠ Warning: Python communication error. Please ensure the backend is running.";
            this.elements.warningMessage.style.display = 'block';
        }
    }

    showSimpleModal(message) {
        const modalHtml = `
            <div id="simple-modal-overlay" class="modal-confirm">
                <div class="modal-confirm-content">
                    <p class="modal-confirm-message">${message}</p>
                    <div class="spacer-10h"></div>
                    <div class="modal-confirm-buttons">
                        <button id="simple-modal-ok-btn" class="btn btn-secondary">OK</button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const simpleModal = document.getElementById('simple-modal-overlay');
        const okBtn = document.getElementById('simple-modal-ok-btn');
        
        setTimeout(() => {
            simpleModal.classList.add('show');
        }, 10);

        okBtn.addEventListener('click', () => {
            simpleModal.classList.remove('show');
            simpleModal.addEventListener('transitionend', () => {
                simpleModal.remove();
            }, { once: true });
        });
    }

    showDeleteConfirmModal(textContent, onConfirm) {
        this.elements.deleteModalMessage.textContent = textContent;
        this.elements.deleteModalOverlay.classList.add('show');

        let yesHandler = () => {
            onConfirm();
            this.elements.deleteModalOverlay.classList.remove('show');
            this.elements.deleteModalYesBtn.removeEventListener('click', yesHandler);
            this.elements.deleteModalNoBtn.removeEventListener('click', noHandler);
        };

        let noHandler = () => {
            this.elements.deleteModalOverlay.classList.remove('show');
            this.elements.deleteModalYesBtn.removeEventListener('click', yesHandler);
            this.elements.deleteModalNoBtn.removeEventListener('click', noHandler);
        };
        
        this.elements.deleteModalYesBtn.addEventListener('click', yesHandler);
        this.elements.deleteModalNoBtn.addEventListener('click', noHandler);
    }

    patchConsoleToPython() {
        const originalLog = console.log;
        const originalWarn = console.warn;
        const originalError = console.error;

        console.log = (...args) => {
            const message = args.map(arg => typeof arg === 'object' ? JSON.stringify(arg) : String(arg)).join(' ');
            try {
                if (typeof this.py_channel !== 'undefined' && this.py_channel.receiveConsoleLog) {
                    this.py_channel.receiveConsoleLog(message);
                }
            } catch (e) {
                originalError("Failed to send log to Python:", e);
            }
            originalLog.apply(console, args);
        };

        console.warn = (...args) => {
            console.log('[WARN]', ...args);
        };

        console.error = (...args) => {
            console.log('[ERROR]', ...args);
        };
    }

    updateCoefficients() {
        this.pointCoefficients = this.equalizerPoints.map(point => {
            return DSPProcessor.getCoefficientsForType(point);
        });

        this.preampLinear = DSPProcessor.dbToLinear(parseFloat(this.elements.preampSlider.value || 0));

        this.bassCoeffs = DSPProcessor.computeBiquadLowShelfCoeffs(
            100,
            parseFloat(this.elements.bassSlider.value || 0)
        );
        this.trebleCoeffs = DSPProcessor.computeBiquadHighShelfCoeffs(
            8000,
            parseFloat(this.elements.trebleSlider.value || 0)
        );

        this.simulatedCurveNeedsUpdate = true;
    }

    getSimulatedGain(freq) {
        let totalGainLin = (typeof this.preampLinear === 'number') ? this.preampLinear : 1.0;

        if (Array.isArray(this.pointCoefficients) && this.pointCoefficients.length > 0) {
            for (let i = 0; i < this.pointCoefficients.length; i++) {
                const coeffs = this.pointCoefficients[i];
                if (coeffs) {
                    const response = DSPProcessor.calcFrequencyResponse(coeffs, freq);
                    totalGainLin *= response;
                }
            }
        }

        if (this.bassCoeffs) {
            totalGainLin *= DSPProcessor.calcFrequencyResponse(this.bassCoeffs, freq);
        }
        if (this.trebleCoeffs) {
            totalGainLin *= DSPProcessor.calcFrequencyResponse(this.trebleCoeffs, freq);
        }

        return DSPProcessor.linearToDb(totalGainLin);
    }


    drawGraph() {
        if (!this.canvas || !this.ctx) return;
        
        const devicePixelRatio = window.devicePixelRatio || 1;
        const width = this.canvas.width / devicePixelRatio;
        const height = this.canvas.height / devicePixelRatio;
        const padding = 25;
        const paddedWidth = width - 2 * padding;
        const paddedHeight = height - 2 * padding;

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);

        // Watermark image
        if (this.watermarkImage.complete) {
            this.ctx.save();
            this.ctx.globalAlpha = 0.06;
            
            const scale = Math.min(paddedWidth / this.watermarkImage.width, paddedHeight / this.watermarkImage.height);
            const imageWidth = this.watermarkImage.width * scale;
            const imageHeight = this.watermarkImage.height * scale;
            const xPos = (-padding)*2;
            const yPos = padding + (paddedHeight - imageHeight) / 2;

            this.ctx.drawImage(this.watermarkImage, xPos, yPos, imageWidth, imageHeight);
            this.ctx.restore();
        }

        // Watermark text
        const watermarkText = 'github.com/PainDe0Mie/AudioEZ';
        this.ctx.save();
        this.ctx.font = '16px Inter';
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.1)'; 
        this.ctx.textAlign = 'left';
        this.ctx.textBaseline = 'bottom';
        this.ctx.fillText(watermarkText, padding, height - padding);
        this.ctx.restore();

        // Grid lines
        this.ctx.lineWidth = 1;
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
        this.ctx.font = '10px Inter';

        const gainsLabels = [-20, -15, -10, -5, 0, 5, 10, 15, 20];
        gainsLabels.forEach(gain => {
            const y = padding + paddedHeight * (1 - (gain - this.MIN_GAIN) / (this.MAX_GAIN - this.MIN_GAIN));
            this.ctx.beginPath();
            this.ctx.moveTo(padding, y);
            this.ctx.lineTo(width - padding, y);
            this.ctx.stroke();
            this.ctx.textAlign = 'left';
            this.ctx.fillText(`${gain} dB`, 5, y + 3);
        });

        this.drawCurve(this.targetEqualizerPoints, '#94a3b8', 1.5, true, padding, paddedWidth, paddedHeight, true);
        
        if (this.earphonesCurve && this.earphonesCurve.length > 0) {
            this.drawCurve(this.earphonesCurve, '#64748b', 2, false, padding, paddedWidth, paddedHeight, true);
        }

        if (this.earphonesCurve && this.earphonesCurve.length > 0 && 
            this.equalizerPoints && this.equalizerPoints.length > 0) {
            
            const finalCurve = this.earphonesCurve.map(({ freq, gain }) => ({
                freq,
                gain: gain + this.getSimulatedGain(freq)
            }));
            
            this.drawCurve(finalCurve, '#3b82f6', 3, false, padding, paddedWidth, paddedHeight, true);
        } else if (this.equalizerPoints && this.equalizerPoints.length > 0) {
            if (this.equalizerPoints && this.equalizerPoints.length > 0) {
                if (this.simulatedCurveNeedsUpdate) {
                    const steps = 1000;
                    const logStep = (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) / steps;
                    this.simulatedCurve = [];
                    for (let i = 0; i <= steps; i++) {
                        const freq = Math.pow(10, this.LOG_MIN_FREQ + i * logStep);
                        this.simulatedCurve.push({
                            freq,
                            gain: this.getSimulatedGain(freq)
                        });
                    }
                    this.simulatedCurveNeedsUpdate = false;
                }
                this.drawCurve(this.simulatedCurve, '#3b82f6', 3, false, padding, paddedWidth, paddedHeight, true);
            }
        }

        // Draw points
        if (this.equalizerPoints.length > 0) {
            this.ctx.font = '12px Inter';
            this.equalizerPoints.forEach((point, i) => {
                if (point && typeof point.gain === 'number') {
                    const logFreq = Math.log10(point.freq);
                    const pointX = padding + (logFreq - this.LOG_MIN_FREQ) / (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) * paddedWidth;
                    const pointY = padding + paddedHeight * (1 - (point.gain - this.MIN_GAIN) / (this.MAX_GAIN - this.MIN_GAIN));

                    this.ctx.beginPath();
                    this.ctx.fillStyle = (point.index === this.selectedPointIndex) ? '#e74c3c' : '#3b82f6';
                    this.ctx.arc(pointX, pointY, 6, 0, 2 * Math.PI);
                    this.ctx.fill();

                    this.ctx.fillStyle = '#e2e8f0';
                    this.ctx.textAlign = 'center';
                    this.ctx.fillText(`${point.gain.toFixed(1)} dB`, pointX, pointY - 12);
                }
            });
        }

        // Frequency labels
        this.ctx.fillStyle = '#94a3b8';
        this.ctx.font = '10px Inter';
        const freqsToDisplay = [60, 250, 1000, 4000, 20000];
        freqsToDisplay.forEach(freq => {
            const logFreq = Math.log10(freq);
            const xPos = padding + (logFreq - this.LOG_MIN_FREQ) / (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) * paddedWidth;
            this.ctx.textAlign = 'center';
            this.ctx.fillText(`${freq} Hz`, xPos, height - 15);

            this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            this.ctx.beginPath();
            this.ctx.moveTo(xPos, padding);
            this.ctx.lineTo(xPos, height - padding);
            this.ctx.stroke();
        });

        //this.updateEqualizerBands(parseInt(this.equalizerPoints.length));
    }

    drawCurve(points, color, lineWidth, dashed = false, padding, paddedWidth, paddedHeight, linear = false) {
        if (!points || points.length === 0) return;
        const { ctx } = this;

        const sortedPoints = [...points].sort((a, b) => a.freq - b.freq);
        const extendedPoints = [
            { freq: this.MIN_FREQ, gain: sortedPoints[0]?.gain ?? 0 },
            ...sortedPoints,
            { freq: this.MAX_FREQ, gain: sortedPoints[sortedPoints.length - 1]?.gain ?? 0 }
        ];

        const logPoints = extendedPoints.map(p => ({
            x: padding + (Math.log10(p.freq) - this.LOG_MIN_FREQ) / (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) * paddedWidth,
            y: padding + paddedHeight * (1 - (p.gain - this.MIN_GAIN) / (this.MAX_GAIN - this.MIN_GAIN))
        }));

        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        if (dashed) {
            ctx.setLineDash([5, 3]);
        } else {
            ctx.setLineDash([]);
        }

        if (linear) {
            // Linear: move to the first point, then line to each subsequent point
            ctx.moveTo(logPoints[0].x, logPoints[0].y);
            for (let i = 1; i < logPoints.length; i++) {
                ctx.lineTo(logPoints[i].x, logPoints[i].y);
            }
        } else {
            // Cubic bezier interpolation
            ctx.moveTo(logPoints[0].x, logPoints[0].y);
            for (let i = 0; i < logPoints.length - 1; i++) {
                const p0 = logPoints[i > 0 ? i - 1 : i];
                const p1 = logPoints[i];
                const p2 = logPoints[i + 1];
                const p3 = logPoints[i + 2 < logPoints.length ? i + 2 : i + 1];

                const cp1x = p1.x + (p2.x - p0.x) / 6;
                const cp1y = p1.y + (p2.y - p0.y) / 6;
                const cp2x = p2.x - (p3.x - p1.x) / 6;
                const cp2y = p2.y - (p3.y - p1.y) / 6;

                ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, p2.x, p2.y);
            }
        }

        ctx.stroke();
        ctx.setLineDash([]);
    }
    
    updateSettings(settings) {
        console.log("Updating UI with settings:", settings);
        
        const isInitialLoad = !this._settingsLoaded;
        this.appSettings = settings;
        if (isInitialLoad) {
            this._settingsLoaded = true;
            this._maybeShowChangelog();
        }

        // Skip updating modal elements if the modal is open — the user is actively
        // editing and the round-trip should NOT revert their in-progress changes
        const modalOpen = this.elements.parametersModal?.classList.contains('show');
        if (!modalOpen) {
            if (this.elements.detectEarphoneCheckbox)
                this.elements.detectEarphoneCheckbox.checked = settings.detect_earphone ?? false;
            if (this.elements.readyOnStartupCheckbox)
                this.elements.readyOnStartupCheckbox.checked = settings.auto_launch ?? false;
            if (this.elements.discordRpcCheckbox)
                this.elements.discordRpcCheckbox.checked = settings.discord_rpc ?? false;
            if (this.elements.launchWithWindowsCheckbox)
                this.elements.launchWithWindowsCheckbox.checked = settings.launch_with_windows ?? false;
            if (this.elements.PersistentStateCheckbox)
                this.elements.PersistentStateCheckbox.checked = settings.persistent_state ?? false;
            if (this.elements.adaptiveFilterState) {
                const wasChecked = this.elements.adaptiveFilterState.checked;
                this.elements.adaptiveFilterState.checked = settings.adaptive_filter ?? false;
                if (!wasChecked && this.elements.adaptiveFilterState.checked) {
                    this.showSimpleModal("Adaptive Filter has been enabled. Please restart the application to apply changes.");
                }
                // Reflect the saved adaptive_config block into the advanced UI.
                if (settings.adaptive_config) {
                    this._applyAdaptiveConfigToUi(settings.adaptive_config);
                }
                this._updateAdaptiveUiVisibility(this.elements.adaptiveFilterState.checked);
            }
            if (this.elements.safeModeCb)
                this.elements.safeModeCb.checked = settings.safe_mode ?? false;
            if (this.elements.safeModeMaxSlider && settings.safe_mode_max_db != null) {
                this.elements.safeModeMaxSlider.value = settings.safe_mode_max_db;
                if (this.elements.safeModeMaxValue) this.elements.safeModeMaxValue.value = settings.safe_mode_max_db;
                if (this.elements.safeModeMaxLabel) this.elements.safeModeMaxLabel.textContent = settings.safe_mode_max_db;
            }
        }

        // Sync .checked class on all switch sliders for Qt WebEngine repaint
        this._syncSwitchSliders();

        if (settings.default_target && this.elements.targetSelect)
            this.elements.targetSelect.value = settings.default_target;
        if (settings.default_headphone && this.elements.defaultHeadphoneSelect)
            this.elements.defaultHeadphoneSelect.value = settings.default_headphone;
        if (settings.default_configuration && this.elements.defaultConfigurationSelect)
            this.elements.defaultConfigurationSelect.value = settings.default_configuration;
    }

    _syncSwitchSliders() {
        document.querySelectorAll('.switch input[type="checkbox"]').forEach(cb => {
            const slider = cb.nextElementSibling;
            if (slider) {
                slider.classList.toggle('checked', cb.checked);
                slider.style.display = 'none';
                slider.offsetHeight;
                slider.style.display = '';
            }
        });
    }

    on_load_finished(ok) {
        if (ok) {
            if (this.appSettings.default_target) {
                this.py_channel.fetchCurve(this.appSettings.default_target);
            }

            if (this.appSettings.auto_launch && this.appSettings.default_headphone && this.appSettings.default_target) {
                setTimeout(() => {
                    this.py_channel.applyAutoEQProfile(
                        this.appSettings.default_headphone,
                        this.appSettings.default_target,
                        this.elements.pointBandsValueInput.value
                    );
                }, 1000);
            }
        }
    }

    // =====================================================================
    // V1.1 — Toast, Undo/Redo, Clip, A/B, Rename, Safe Mode, Changelog
    // =====================================================================

    showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        requestAnimationFrame(() => {
            requestAnimationFrame(() => toast.classList.add('toast-show'));
        });
        setTimeout(() => {
            toast.classList.remove('toast-show');
            toast.addEventListener('transitionend', () => toast.remove(), { once: true });
        }, duration);
    }

    _snapshotState() {
        return {
            points: this.equalizerPoints.map(p => ({ ...p })),
            preamp: parseFloat(this.elements.preampSlider.value),
            bass:   parseFloat(this.elements.bassSlider.value),
            treble: parseFloat(this.elements.trebleSlider.value)
        };
    }

    _pushHistory() {
        if (this._historyPaused) return;
        this._undoStack.push(this._snapshotState());
        if (this._undoStack.length > 50) this._undoStack.shift();
        this._redoStack = [];
    }

    _applySnapshot(snap) {
        this._historyPaused = true;
        this.equalizerPoints = snap.points.map(p => ({ ...p }));
        this.elements.preampSlider.value = snap.preamp;
        this.elements.preampValue.value  = snap.preamp;
        this.elements.bassSlider.value   = snap.bass;
        this.elements.bassValue.value    = snap.bass;
        this.elements.trebleSlider.value = snap.treble;
        this.elements.trebleValue.value  = snap.treble;
        if (this.py_channel) {
            this.py_channel.setPreampGain(snap.preamp);
            this.py_channel.setBassGain(snap.bass);
            this.py_channel.setTrebleGain(snap.treble);
            snap.points.forEach(p => {
                this.py_channel.setEqualizerPointParameter(p.index, 'gain', p.gain);
                this.py_channel.setEqualizerPointParameter(p.index, 'freq', p.freq);
                this.py_channel.setEqualizerPointParameter(p.index, 'q',    p.q);
                this.py_channel.setEqualizerPointParameter(p.index, 'type', this.filterTypeCodes[p.type] ?? 0);
            });
        }
        this.updateCoefficients();
        this.drawGraph();
        this._historyPaused = false;
    }

    undo() {
        if (!this._undoStack.length) { this.showToast('Nothing to undo.', 'info', 1500); return; }
        this._redoStack.push(this._snapshotState());
        this._applySnapshot(this._undoStack.pop());
        this.showToast('Undo', 'info', 1200);
    }

    redo() {
        if (!this._redoStack.length) { this.showToast('Nothing to redo.', 'info', 1500); return; }
        this._undoStack.push(this._snapshotState());
        this._applySnapshot(this._redoStack.pop());
        this.showToast('Redo', 'info', 1200);
    }

    _checkClip() {
        if (!this.equalizerPoints.length) return;
        const maxGain = Math.max(
            ...this.equalizerPoints.map(p => p.gain),
            parseFloat(this.elements.bassSlider.value) || 0,
            parseFloat(this.elements.trebleSlider.value) || 0
        );
        const preamp = parseFloat(this.elements.preampSlider.value) || 0;
        const clipping = (preamp + maxGain) > 0;
        if (this.elements.clipIndicator) {
            this.elements.clipIndicator.classList.toggle('visible', clipping);
        }
    }

    _abToggle() {
        if (!this._abSlotA) {
            this._abSlotA = this._snapshotState();
            this._abActive = false;
            this.elements.abBtnLabel.textContent = 'A/B: A saved';
            this.elements.abBtn.classList.add('ab-active');
            this.showToast('A/B: reference saved. Click again to compare.', 'info');
            return;
        }
        if (!this._abActive) {
            this._abSlotB = this._snapshotState();
            this._applySnapshot(this._abSlotA);
            this._abActive = true;
            this.elements.abBtnLabel.textContent = 'A/B: showing A';
        } else {
            this._applySnapshot(this._abSlotB);
            this._abActive = false;
            this.elements.abBtnLabel.textContent = 'A/B: showing B';
        }
    }

    _abReset() {
        this._abSlotA = null;
        this._abSlotB = null;
        this._abActive = false;
        this.elements.abBtnLabel.textContent = 'A/B: off';
        this.elements.abBtn.classList.remove('ab-active');
        this.showToast('A/B reset.', 'info', 1500);
    }

    _openRenameModal(currentName) {
        const { renameModal, renameInput, renameModalOk, renameModalCancel } = this.elements;
        renameInput.value = currentName;
        renameModal.classList.add('show');
        renameInput.focus();
        renameInput.select();

        const doRename = () => {
            const newName = renameInput.value.trim();
            renameModal.classList.remove('show');
            if (!newName || newName === currentName) { cleanup(); return; }
            if (this.py_channel) this.py_channel.renameConfig(currentName, newName);
            cleanup();
        };
        const doCancel = () => { renameModal.classList.remove('show'); cleanup(); };
        const onKey = (e) => {
            if (e.key === 'Enter')  doRename();
            if (e.key === 'Escape') doCancel();
        };
        const cleanup = () => {
            renameModalOk.removeEventListener('click', doRename);
            renameModalCancel.removeEventListener('click', doCancel);
            renameInput.removeEventListener('keydown', onKey);
        };
        renameModalOk.addEventListener('click', doRename);
        renameModalCancel.addEventListener('click', doCancel);
        renameInput.addEventListener('keydown', onKey);
    }

    // ========================================================================
    //  Adaptive Filter — advanced UI wiring
    // ========================================================================

    _adaptiveProfileList() {
        return ["Speech", "Movie", "Music", "Electronic", "Rock", "Pop",
                "Classical", "Hip-Hop", "Jazz", "Singing", "Ambient", "Acoustic"];
    }

    _setupAdaptiveAdvancedControls() {
        if (this._adaptiveAdvancedWired) return;
        this._adaptiveAdvancedWired = true;

        const e = this.elements;

        // Collapsible toggle
        if (e.adaptiveAdvancedToggle) {
            e.adaptiveAdvancedToggle.addEventListener('click', () => {
                const body = e.adaptiveAdvancedBody;
                if (!body) return;
                const open = body.style.display !== 'none';
                body.style.display = open ? 'none' : 'flex';
                e.adaptiveAdvancedToggle.textContent =
                    open ? 'Advanced parameters ▾' : 'Advanced parameters ▴';
            });
        }

        // Sliders — bind label updates and debounce save
        const sliderBindings = [
            [e.adaptiveSpeechThreshold, e.adaptiveSpeechThresholdVal, v => v.toFixed(2)],
            [e.adaptiveMusicThreshold,  e.adaptiveMusicThresholdVal,  v => v.toFixed(2)],
            [e.adaptiveHysteresis,      e.adaptiveHysteresisVal,      v => `${v.toFixed(1)}s`],
            [e.adaptiveCooldown,        e.adaptiveCooldownVal,        v => `${v.toFixed(1)}s`],
            [e.adaptiveTransition,      e.adaptiveTransitionVal,      v => `${v.toFixed(1)}s`],
        ];
        sliderBindings.forEach(([slider, label, fmt]) => {
            if (!slider) return;
            slider.addEventListener('input', () => {
                if (label) label.textContent = fmt(parseFloat(slider.value));
                this._scheduleAdaptiveSave();
            });
        });

        if (e.adaptiveManualOverride) {
            e.adaptiveManualOverride.addEventListener('change', () => this._scheduleAdaptiveSave());
        }

        // Build the profile chips grid
        if (e.adaptiveProfileGrid && !e.adaptiveProfileGrid.children.length) {
            this._adaptiveProfileList().forEach(name => {
                const chip = document.createElement('label');
                chip.className = 'adaptive-profile-chip active';
                chip.dataset.profile = name;
                chip.innerHTML = `<input type="checkbox" checked> <span>${name}</span>`;
                const cb = chip.querySelector('input');
                cb.addEventListener('change', () => {
                    chip.classList.toggle('active', cb.checked);
                    this._scheduleAdaptiveSave();
                });
                e.adaptiveProfileGrid.appendChild(chip);
            });
        }
    }

    _scheduleAdaptiveSave() {
        clearTimeout(this._adaptiveSaveTimer);
        this._adaptiveSaveTimer = setTimeout(() => this.saveSettingsToPython(), 350);
    }

    _collectAdaptiveConfigFromUi() {
        const e = this.elements;
        const enabled = [];
        if (e.adaptiveProfileGrid) {
            e.adaptiveProfileGrid.querySelectorAll('.adaptive-profile-chip').forEach(chip => {
                const cb = chip.querySelector('input');
                if (cb && cb.checked) enabled.push(chip.dataset.profile);
            });
        }
        return {
            speech_threshold:        parseFloat(e.adaptiveSpeechThreshold?.value ?? 0.6),
            music_genre_threshold:   parseFloat(e.adaptiveMusicThreshold?.value  ?? 0.4),
            hysteresis_delay:        parseFloat(e.adaptiveHysteresis?.value      ?? 8),
            cooldown_period:         parseFloat(e.adaptiveCooldown?.value        ?? 12),
            transition_duration:     parseFloat(e.adaptiveTransition?.value      ?? 1.5),
            manual_override_pause:   e.adaptiveManualOverride?.checked ?? true,
            enabled_profiles:        enabled.length ? enabled : null,
        };
    }

    _applyAdaptiveConfigToUi(cfg) {
        if (!cfg) return;
        const e = this.elements;
        const setSlider = (el, label, value, fmt) => {
            if (el && value != null) {
                el.value = value;
                if (label) label.textContent = fmt(parseFloat(value));
            }
        };
        setSlider(e.adaptiveSpeechThreshold, e.adaptiveSpeechThresholdVal, cfg.speech_threshold,        v => v.toFixed(2));
        setSlider(e.adaptiveMusicThreshold,  e.adaptiveMusicThresholdVal,  cfg.music_genre_threshold,   v => v.toFixed(2));
        setSlider(e.adaptiveHysteresis,      e.adaptiveHysteresisVal,      cfg.hysteresis_delay,        v => `${v.toFixed(1)}s`);
        setSlider(e.adaptiveCooldown,        e.adaptiveCooldownVal,        cfg.cooldown_period,         v => `${v.toFixed(1)}s`);
        setSlider(e.adaptiveTransition,      e.adaptiveTransitionVal,      cfg.transition_duration,     v => `${v.toFixed(1)}s`);
        if (e.adaptiveManualOverride && cfg.manual_override_pause != null) {
            e.adaptiveManualOverride.checked = !!cfg.manual_override_pause;
        }
        if (e.adaptiveProfileGrid && cfg.enabled_profiles) {
            const set = new Set(cfg.enabled_profiles);
            e.adaptiveProfileGrid.querySelectorAll('.adaptive-profile-chip').forEach(chip => {
                const on = set.has(chip.dataset.profile);
                const cb = chip.querySelector('input');
                if (cb) cb.checked = on;
                chip.classList.toggle('active', on);
            });
        }
    }

    _updateAdaptiveUiVisibility(enabled) {
        const e = this.elements;
        if (e.adaptiveStatusRow)  e.adaptiveStatusRow.style.display  = enabled ? 'flex' : 'none';
        if (e.adaptiveAdvanced)   e.adaptiveAdvanced.style.display   = enabled ? 'block' : 'none';
        if (!enabled && e.adaptiveAdvancedBody) {
            e.adaptiveAdvancedBody.style.display = 'none';
            if (e.adaptiveAdvancedToggle)
                e.adaptiveAdvancedToggle.textContent = 'Advanced parameters ▾';
        }
    }

    _renderAdaptiveStatus(status) {
        const e = this.elements;
        if (!e.adaptiveStatusRow) return;
        const detection = status?.detection || 'idle';
        const confidence = (status?.confidence != null) ? Math.round(status.confidence * 100) : null;
        const profile = status?.profile || 'default';
        const paused = !!status?.paused;

        e.adaptiveStatusRow.classList.toggle('paused', paused);
        if (e.adaptiveStatusText) {
            const label = paused
                ? `Paused — ${detection}`
                : (confidence != null ? `${detection} · ${confidence}%` : detection);
            e.adaptiveStatusText.textContent = label;
        }
        if (e.adaptiveStatusProfile) {
            e.adaptiveStatusProfile.textContent = profile === 'default' ? '—' : profile;
        }
    }

    _openTagPicker(presetName) {
        const { tagModal, tagModalTitle, tagModalSelect, tagModalOk, tagModalCancel } = this.elements;
        if (!tagModal || !tagModalSelect) return;
        tagModalTitle.textContent = `Tag preset "${presetName}":`;
        tagModalSelect.value = this.presetTags?.[presetName] || "";
        tagModal.classList.add('show');

        const doApply = () => {
            const tag = tagModalSelect.value || "";
            tagModal.classList.remove('show');
            if (this.py_channel && this.py_channel.setPresetTag) {
                this.py_channel.setPresetTag(presetName, tag);
            }
            // Optimistically update local cache so the UI reflects it instantly
            if (tag) this.presetTags[presetName] = tag;
            else delete this.presetTags[presetName];
            this._renderConfigList(this.elements.configListSelect.value);
            cleanup();
        };
        const doCancel = () => { tagModal.classList.remove('show'); cleanup(); };
        const onKey = (e) => {
            if (e.key === 'Enter')  doApply();
            if (e.key === 'Escape') doCancel();
        };
        const cleanup = () => {
            tagModalOk.removeEventListener('click', doApply);
            tagModalCancel.removeEventListener('click', doCancel);
            tagModalSelect.removeEventListener('keydown', onKey);
        };
        tagModalOk.addEventListener('click', doApply);
        tagModalCancel.addEventListener('click', doCancel);
        tagModalSelect.addEventListener('keydown', onKey);
    }

    _maybeShowChangelog() {
        const CURRENT_VERSION = 'v1.1';
        if (this.appSettings?.last_seen_version !== CURRENT_VERSION) {
            setTimeout(() => this.elements.changelogModal?.classList.add('show'), 800);
        }
    }

    _closeChangelog() {
        this.elements.changelogModal?.classList.remove('show');
        if (this.py_channel) this.py_channel.setLastSeenVersion('v1.1');
    }

    _applySafeMode() {
        const enabled = this.elements.safeModeCb?.checked ?? false;
        const maxDb   = parseFloat(this.elements.safeModeMaxSlider?.value ?? 12);
        if (this.py_channel) this.py_channel.setSafeMode(enabled, maxDb);
    }

    _resetEQ() {
        this._pushHistory();
        this.equalizerPoints.forEach(p => { p.gain = 0; });
        this.elements.preampSlider.value = 0;
        this.elements.preampValue.value = 0;
        this.elements.bassSlider.value = 0;
        this.elements.bassValue.value = 0;
        this.elements.trebleSlider.value = 0;
        this.elements.trebleValue.value = 0;

        if (this.py_channel) {
            this.py_channel.setPreampGain(0);
            this.py_channel.setBassGain(0);
            this.py_channel.setTrebleGain(0);
            this.equalizerPoints.forEach(p => {
                this.py_channel.setEqualizerPointParameter(p.index, 'gain', 0);
            });
        }

        this.selectedPointIndex = -1;
        this.hidePointParameters();
        this.updateCoefficients();
        this.drawGraph();
        this.showToast('EQ reset to flat.', 'info', 2000);
    }

    _autoPreamp() {
        if (!this.equalizerPoints.length) return;

        // Find the peak gain across the full simulated curve
        let peakGain = -Infinity;
        const steps = 500;
        const logStep = (this.LOG_MAX_FREQ - this.LOG_MIN_FREQ) / steps;
        for (let i = 0; i <= steps; i++) {
            const freq = Math.pow(10, this.LOG_MIN_FREQ + i * logStep);
            // getSimulatedGain already includes current preamp — we want the gain WITHOUT preamp
            let totalLin = 1.0;
            for (const coeffs of this.pointCoefficients) {
                if (coeffs) totalLin *= DSPProcessor.calcFrequencyResponse(coeffs, freq);
            }
            if (this.bassCoeffs) totalLin *= DSPProcessor.calcFrequencyResponse(this.bassCoeffs, freq);
            if (this.trebleCoeffs) totalLin *= DSPProcessor.calcFrequencyResponse(this.trebleCoeffs, freq);
            const gainDb = DSPProcessor.linearToDb(totalLin);
            if (gainDb > peakGain) peakGain = gainDb;
        }

        // Optimal preamp is the negative of the peak
        const optimal = peakGain > 0 ? -Math.ceil(peakGain * 10) / 10 : 0;

        this._pushHistory();
        this.elements.preampSlider.value = optimal;
        this.elements.preampValue.value = optimal;
        if (this.py_channel) this.py_channel.setPreampGain(optimal);
        this.updateCoefficients();
        this.drawGraph();
        this.showToast(`Auto-preamp: ${optimal.toFixed(1)} dB`, 'success', 2000);
    }

    setupV11EventListeners() {
        const {
            newsBtn, undoBtn, redoBtn, abBtn, exportApoIncludeButton,
            safeModeCb, safeModeMaxSlider, safeModeMaxValue, safeModeMaxLabel,
            closeChangelogModal, closeChangelogOk, configListSelect
        } = this.elements;

        if (newsBtn) newsBtn.addEventListener('click', () => {
            this.elements.changelogModal?.classList.add('show');
        });

        if (undoBtn) undoBtn.addEventListener('click', () => this.undo());
        if (redoBtn) redoBtn.addEventListener('click', () => this.redo());

        if (abBtn) {
            abBtn.addEventListener('click',    ()  => this._abToggle());
            abBtn.addEventListener('dblclick', (e) => { e.stopPropagation(); this._abReset(); });
        }

        if (exportApoIncludeButton) {
            exportApoIncludeButton.addEventListener('click', () => {
                if (this.elements.exportDropdown) this.elements.exportDropdown.classList.remove('open');
                if (this.py_channel) this.py_channel.exportToApoInclude();
            });
        }

        // Auto-preamp
        const { autoPreampBtn } = this.elements;
        if (autoPreampBtn) autoPreampBtn.addEventListener('click', () => this._autoPreamp());

        if (safeModeCb) safeModeCb.addEventListener('change', () => this._applySafeMode());

        if (safeModeMaxSlider) {
            safeModeMaxSlider.addEventListener('input', (e) => {
                const v = parseInt(e.target.value);
                if (safeModeMaxValue) safeModeMaxValue.value = v;
                if (safeModeMaxLabel) safeModeMaxLabel.textContent = v;
                this._applySafeMode();
            });
        }
        if (safeModeMaxValue) {
            safeModeMaxValue.addEventListener('input', (e) => {
                const v = parseInt(e.target.value);
                if (safeModeMaxSlider) safeModeMaxSlider.value = v;
                if (safeModeMaxLabel) safeModeMaxLabel.textContent = v;
                this._applySafeMode();
            });
        }

        // Rename config button (replaces dblclick which doesn't work on <select>)
        const { renameConfigBtn } = this.elements;
        if (renameConfigBtn) {
            renameConfigBtn.addEventListener('click', () => {
                const selected = configListSelect.value;
                if (!selected || selected === 'Default') {
                    this.showToast("Cannot rename the default configuration.", 'error', 2000);
                    return;
                }
                this._openRenameModal(selected);
            });
        }

        // Tag config button — assign a tag to the selected preset
        const { tagConfigBtn, tagFilterSelect } = this.elements;
        if (tagConfigBtn) {
            tagConfigBtn.addEventListener('click', () => {
                const selected = configListSelect.value;
                if (!selected || selected === 'Default') {
                    this.showToast("Cannot tag the default configuration.", 'error', 2000);
                    return;
                }
                this._openTagPicker(selected);
            });
        }

        // Tag filter dropdown — re-render the config list whenever it changes
        if (tagFilterSelect) {
            tagFilterSelect.addEventListener('change', (e) => {
                this.activeTagFilter = e.target.value || "";
                const current = configListSelect.value;
                this._renderConfigList(current);
            });
        }

        // Reset EQ button
        const { resetEqBtn } = this.elements;
        if (resetEqBtn) resetEqBtn.addEventListener('click', () => this._resetEQ());

        if (closeChangelogModal) closeChangelogModal.addEventListener('click', () => this._closeChangelog());
        if (closeChangelogOk)   closeChangelogOk.addEventListener('click',   () => this._closeChangelog());
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            const tag = document.activeElement?.tagName;
            if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
            if (e.ctrlKey && e.key === 'z') { e.preventDefault(); this.undo(); }
            if (e.ctrlKey && e.key === 'y') { e.preventDefault(); this.redo(); }

            // Arrow keys to nudge selected point
            if (this.selectedPointIndex !== -1 && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                e.preventDefault();
                const point = this.equalizerPoints.find(p => p.index === this.selectedPointIndex);
                if (!point) return;

                this._pushHistory();
                const fine = e.shiftKey;

                if (e.key === 'ArrowUp') {
                    point.gain = Math.min(this.MAX_GAIN, point.gain + (fine ? 0.1 : 0.5));
                    point.gain = parseFloat(point.gain.toFixed(1));
                } else if (e.key === 'ArrowDown') {
                    point.gain = Math.max(this.MIN_GAIN, point.gain - (fine ? 0.1 : 0.5));
                    point.gain = parseFloat(point.gain.toFixed(1));
                } else if (e.key === 'ArrowRight') {
                    const logFreq = Math.log10(point.freq);
                    const step = fine ? 0.01 : 0.05;
                    const newLog = Math.min(this.LOG_MAX_FREQ, logFreq + step);
                    point.freq = Math.round(Math.pow(10, newLog));
                } else if (e.key === 'ArrowLeft') {
                    const logFreq = Math.log10(point.freq);
                    const step = fine ? 0.01 : 0.05;
                    const newLog = Math.max(this.LOG_MIN_FREQ, logFreq - step);
                    point.freq = Math.round(Math.pow(10, newLog));
                }

                if (this.py_channel) {
                    this.py_channel.setEqualizerPointParameter(point.index, 'gain', point.gain);
                    this.py_channel.setEqualizerPointParameter(point.index, 'freq', point.freq);
                }

                this.showPointParameters(point);
                this.updateCoefficients();
                this.drawGraph();
            }
        });
    }
}


class DSPProcessor {
    static dbToLinear(db) {
        return Math.pow(10, db / 20);
    }

    static linearToDb(linear) {
        return 20 * Math.log10(Math.max(linear, 1e-10));
    }

    // Optimized biquad coefficient calculations
    static computeBiquadPeakCoeffs(fc, Q, gainDb, fs = 48000) {
        const A = Math.pow(10, gainDb / 40);
        const w0 = 2 * Math.PI * fc / fs;
        const sin_w0 = Math.sin(w0);
        const cos_w0 = Math.cos(w0);
        const alpha = sin_w0 / (2 * Q);

        const b0 = 1 + alpha * A;
        const b1 = -2 * cos_w0;
        const b2 = 1 - alpha * A;
        const a0 = 1 + alpha / A;
        const a1 = -2 * cos_w0;
        const a2 = 1 - alpha / A;

        return { 
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1, a1: a1 / a0, a2: a2 / a0 
        };
    }

    static computeBiquadLowShelfCoeffs(fc, gainDb, Q = Math.SQRT1_2, fs = 48000) {
        // RBJ low shelf normalized to a0 = 1
        const A = Math.pow(10, gainDb / 40);
        const w0 = 2 * Math.PI * fc / fs;
        const sin_w0 = Math.sin(w0);
        const cos_w0 = Math.cos(w0);
        const alpha = sin_w0 / (2 * Q);
        const sqrtA = Math.sqrt(A);
        const sqrt2Aalpha = 2 * sqrtA * alpha;

        let b0 = A * ((A + 1) - (A - 1) * cos_w0 + sqrt2Aalpha);
        let b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0);
        let b2 = A * ((A + 1) - (A - 1) * cos_w0 - sqrt2Aalpha);
        let a0 = (A + 1) + (A - 1) * cos_w0 + sqrt2Aalpha;
        let a1 = -2 * ((A - 1) + (A + 1) * cos_w0);
        let a2 = (A + 1) + (A - 1) * cos_w0 - sqrt2Aalpha;

        // normalize
        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1, a1: a1 / a0, a2: a2 / a0
        };
    }

    static computeBiquadHighShelfCoeffs(fc, gainDb, Q = Math.SQRT1_2, fs = 48000) {
        // RBJ high shelf normalized to a0 = 1
        const A = Math.pow(10, gainDb / 40);
        const w0 = 2 * Math.PI * fc / fs;
        const sin_w0 = Math.sin(w0);
        const cos_w0 = Math.cos(w0);
        const alpha = sin_w0 / (2 * Q);
        const sqrtA = Math.sqrt(A);
        const sqrt2Aalpha = 2 * sqrtA * alpha;

        let b0 = A * ((A + 1) + (A - 1) * cos_w0 + sqrt2Aalpha);
        let b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0);
        let b2 = A * ((A + 1) + (A - 1) * cos_w0 - sqrt2Aalpha);
        let a0 = (A + 1) - (A - 1) * cos_w0 + sqrt2Aalpha;
        let a1 = 2 * ((A - 1) - (A + 1) * cos_w0);
        let a2 = (A + 1) - (A - 1) * cos_w0 - sqrt2Aalpha;

        // normalize
        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1, a1: a1 / a0, a2: a2 / a0
        };
    }

    static computeBiquadLowPassCoeffs(fc, Q, fs = 48000) {
        const w0 = 2 * Math.PI * fc / fs;
        const alpha = Math.sin(w0) / (2 * Q);
        const cos_w0 = Math.cos(w0);

        const b0 = (1 - cos_w0) / 2;
        const b1 = 1 - cos_w0;
        const b2 = (1 - cos_w0) / 2;
        const a0 = 1 + alpha;
        const a1 = -2 * cos_w0;
        const a2 = 1 - alpha;

        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1,
            a1: a1 / a0, a2: a2 / a0
        };
    }

    static computeBiquadHighPassCoeffs(fc, Q, fs = 48000) {
        const w0 = 2 * Math.PI * fc / fs;
        const alpha = Math.sin(w0) / (2 * Q);
        const cos_w0 = Math.cos(w0);

        const b0 = (1 + cos_w0) / 2;
        const b1 = -(1 + cos_w0);
        const b2 = (1 + cos_w0) / 2;
        const a0 = 1 + alpha;
        const a1 = -2 * cos_w0;
        const a2 = 1 - alpha;

        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1,
            a1: a1 / a0, a2: a2 / a0
        };
    }

    static computeBiquadBandPassCoeffs(fc, Q, fs = 48000) {
        const w0 = 2 * Math.PI * fc / fs;
        const sin_w0 = Math.sin(w0);
        const cos_w0 = Math.cos(w0);
        const alpha = sin_w0 / (2 * Q);

        // RBJ band-pass (constant skirt) uses alpha for b0/b2
        const b0 = alpha;
        const b1 = 0;
        const b2 = -alpha;
        const a0 = 1 + alpha;
        const a1 = -2 * cos_w0;
        const a2 = 1 - alpha;

        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1,
            a1: a1 / a0, a2: a2 / a0
        };
    }

    static computeBiquadNotchCoeffs(fc, Q, fs = 48000) {
        const w0 = 2 * Math.PI * fc / fs;
        const alpha = Math.sin(w0) / (2 * Q);
        const cos_w0 = Math.cos(w0);

        const b0 = 1;
        const b1 = -2 * cos_w0;
        const b2 = 1;
        const a0 = 1 + alpha;
        const a1 = -2 * cos_w0;
        const a2 = 1 - alpha;

        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1,
            a1: a1 / a0, a2: a2 / a0
        };
    }

    static computeBiquadAllPassCoeffs(fc, Q, fs = 48000) {
        const w0 = 2 * Math.PI * fc / fs;
        const alpha = Math.sin(w0) / (2 * Q);
        const cos_w0 = Math.cos(w0);

        const b0 = 1 - alpha;
        const b1 = -2 * cos_w0;
        const b2 = 1 + alpha;
        const a0 = 1 + alpha;
        const a1 = -2 * cos_w0;
        const a2 = 1 - alpha;

        return {
            b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
            a0: 1,
            a1: a1 / a0, a2: a2 / a0
        };
    }

    static calcFrequencyResponse(coeffs, freq, fs = 48000) {
        const w = 2 * Math.PI * freq / fs;
        const cos_w = Math.cos(w);
        const cos_2w = Math.cos(2 * w);
        const sin_w = Math.sin(w);
        const sin_2w = Math.sin(2 * w);

        const num_real = coeffs.b0 + coeffs.b1 * cos_w + coeffs.b2 * cos_2w;
        const num_imag = -coeffs.b1 * sin_w - coeffs.b2 * sin_2w;

        const den_real = 1 + coeffs.a1 * cos_w + coeffs.a2 * cos_2w;
        const den_imag = -coeffs.a1 * sin_w - coeffs.a2 * sin_2w;

        const num_mag = Math.hypot(num_real, num_imag);
        const den_mag = Math.hypot(den_real, den_imag);

        return num_mag / Math.max(den_mag, 1e-12);
    }

    static getCoefficientsForType(point) {
        if (!point) return null;
        
        switch (point.type) {
            case 'LP': return this.computeBiquadLowPassCoeffs(point.freq, point.q);
            case 'HP': return this.computeBiquadHighPassCoeffs(point.freq, point.q);
            case 'LS': return this.computeBiquadLowShelfCoeffs(point.freq, point.gain);
            case 'LSQ': return this.computeBiquadLowShelfCoeffs(point.freq, point.gain, point.q);
            case 'HS': return this.computeBiquadHighShelfCoeffs(point.freq, point.gain);
            case 'HSQ': return this.computeBiquadHighShelfCoeffs(point.freq, point.gain, point.q);
            case 'PK': return this.computeBiquadPeakCoeffs(point.freq, point.q, point.gain);
            case 'BP': return this.computeBiquadBandPassCoeffs(point.freq, point.q);
            case 'NO': return this.computeBiquadNotchCoeffs(point.freq, point.q);
            case 'AP': return this.computeBiquadAllPassCoeffs(point.freq, point.q);
            case 'BPII': return this.computeBiquadBandPassCoeffs(point.freq, point.q);
            case 'APII': return this.computeBiquadAllPassCoeffs(point.freq, point.q);
            case 'LPII': return this.computeBiquadLowPassCoeffs(point.freq, point.q);
            case 'HPII': return this.computeBiquadHighPassCoeffs(point.freq, point.q);
            default: return this.computeBiquadPeakCoeffs(point.freq, point.q, point.gain);
        }
    }
}

const audioEZApp = new AudioEZApp();

window.updateSettingsFromPython = function(settingsJson) {
    try {
        const settings = JSON.parse(settingsJson);
        if (audioEZApp) {
            audioEZApp.updateSettings(settings);
        }
    } catch (e) {
        console.error("Error updating settings from Python:", e);
    }
};

window.onload = function() {
    if (typeof qt !== 'undefined' && qt.webChannelTransport) {
        audioEZApp.setupWebChannel();
    } else {
        console.warn("Qt WebChannel non disponible, nouvel essai dans 50ms...");
        setTimeout(window.onload, 50);
    }
};