        // --- API Config ---
        // --- API Config ---
        // Automatically detects if running locally or on Render
        const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
            ? "http://localhost:8000" 
            : window.location.origin; 

        const state = {
            currentPage: 'home',
            registrationStep: 1,
            faceShots: 0,
            otpTimer: null,
            videoStream: null,
            lastFaceB64: null,
            // Active Liveness State Machine
            livenessState: 'WAITING_FACE', // WAITING_FACE -> CHALLENGE -> BLINK_TEST -> SUCCESS
            currentChallenge: null, // 'SMILE', 'TURN_LEFT', 'TURN_RIGHT'
            challengePassed: false,
            eyesClosedFrames: 0,
            consecutiveOpenFrames: 0,
            hasSeenOpenEyes: false, // Ensures we see open eyes before counting a blink
            faceMesh: null,
            camera: null
        };

        // --- Helper: Eye Aspect Ratio (EAR) ---
        function calculateEAR(eyeLandmarks, landmarks) {
            const p1 = landmarks[eyeLandmarks[0]];
            const p2 = landmarks[eyeLandmarks[1]];
            const p3 = landmarks[eyeLandmarks[2]];
            const p4 = landmarks[eyeLandmarks[3]];
            const p5 = landmarks[eyeLandmarks[4]];
            const p6 = landmarks[eyeLandmarks[5]];

            const dist = (a, b) => Math.sqrt(Math.pow(a.x - b.x, 2) + Math.pow(a.y - b.y, 2));
            const v1 = dist(p2, p6);
            const v2 = dist(p3, p5);
            const h = dist(p1, p4);

            return (v1 + v2) / (2.0 * h);
        }

        // --- Helper: Mouth Aspect Ratio (MAR) ---
        function calculateMAR(landmarks) {
            // Mouth corners: 61, 291
            // Upper lip inner: 13
            // Lower lip inner: 14
            const pLeft = landmarks[61];
            const pRight = landmarks[291];
            const pTop = landmarks[13];
            const pBottom = landmarks[14];

            const dist = (a, b) => Math.sqrt(Math.pow(a.x - b.x, 2) + Math.pow(a.y - b.y, 2));
            const h = dist(pLeft, pRight);
            const v = dist(pTop, pBottom);

            return v / h;
        }

        // --- Helper: Head Yaw (Turn Detection) ---
        function calculateYaw(landmarks) {
            // Nose tip: 1
            // Left eye center approx: 33
            // Right eye center approx: 263
            const nose = landmarks[1];
            const leftEye = landmarks[33];
            const rightEye = landmarks[263];

            // Ratio of Left-Eye-to-Nose vs Right-Eye-to-Nose
            // If nose is closer to left eye, head is turned Right. 
            // Note: landmarks.x is normalized 0-1 across the width
            const leftDist = nose.x - leftEye.x;
            const rightDist = rightEye.x - nose.x;

            // If they are looking straight ahead, the ratio is ~1.0
            if (rightDist === 0) return 1.0;
            return leftDist / rightDist;
        }
        // --- Auth Logic ---
        async function handleLogin() {
            const u = document.getElementById('login-username').value;
            const p = document.getElementById('login-password').value;

            if (!u || !p) return showToast("Enter credentials");

            try {
                const formData = new FormData();
                formData.append('username', u);
                formData.append('password', p);

                const res = await fetch(`${API_BASE}/login`, {
                    method: 'POST',
                    body: formData
                });

                if (res.ok) {
                    const data = await res.json();
                    state.token = data.access_token;
                    state.username = u;
                    localStorage.setItem('faceauth_token', state.token);
                    localStorage.setItem('faceauth_user', u);
                    initAuth();
                    showPage('home');
                    showToast("Security Access Granted", "success");
                } else {
                    const data = await res.json();
                    showToast(data.message || "Identity Verification Failed");
                }
            } catch (err) {
                showToast("Server Connection Lost");
            }
        }

        function logout() {
            state.token = null;
            state.username = null;
            localStorage.removeItem('faceauth_token');
            localStorage.removeItem('faceauth_user');
            initAuth();
            showPage('home');
        }

        // --- Navigation ---
        function showPage(pageId) {
            state.currentPage = pageId;
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(`${pageId}-page`).classList.add('active');

            // Stop camera if leaving cam pages
            if (pageId !== 'transaction' && pageId !== 'register') {
                stopCamera();
            }

            // Reset flows
            if (pageId === 'transaction') resetTransaction();
            if (pageId === 'register') resetRegistration();
            if (pageId === 'dashboard') loadDashboard();
        }

        // --- Dashboard ---
        async function loadDashboard() {
            console.log("[API] Fetching dashboard data...");
            try {
                // Fetch stats, users, and transactions concurrently
                const [statsRes, usersRes, txRes] = await Promise.all([
                    fetch(`${API_BASE}/stats`),
                    fetch(`${API_BASE}/users`),
                    fetch(`${API_BASE}/transactions`)
                ]);

                if (!statsRes.ok || !usersRes.ok || !txRes.ok) {
                    throw new Error('Failed to load one or more dashboard endpoints');
                }

                const stats = await statsRes.json();
                const users = await usersRes.json();
                const transactions = await txRes.json();
                
                console.log("[API] Stats:", stats);
                console.log("[API] Users:", users);

                // Stats Update
                document.getElementById('stat-total-users').textContent = users.length || 0;
                document.getElementById('stat-total-tx').textContent = stats.total_transactions || 0;
                document.getElementById('stat-blocked-tx').textContent = stats.blocked || 0;

                // Users table
                const tbody = document.getElementById('users-table-body');
                if (!users || users.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--text-dim);">No users registered yet</td></tr>';
                } else {
                    tbody.innerHTML = users.map((u, i) => `
                        <tr style="animation: fadeIn 0.3s ease ${i * 0.05}s both;">
                            <td style="padding: 0.8rem 1rem; border-bottom: 1px solid var(--glass-border);">${i + 1}</td>
                            <td style="padding: 0.8rem 1rem; border-bottom: 1px solid var(--glass-border); font-weight: 600;">${u.user_id}</td>
                            <td style="padding: 0.8rem 1rem; border-bottom: 1px solid var(--glass-border);">${u.email || '—'}</td>
                            <td style="padding: 0.8rem 1rem; border-bottom: 1px solid var(--glass-border); font-family: monospace; letter-spacing: 1px;">${u.card_number || '—'}</td>
                            <td style="padding: 0.8rem 1rem; border-bottom: 1px solid var(--glass-border);">
                                <span style="padding: 0.2rem 0.6rem; border-radius: 20px; font-size: 0.75rem; font-weight: 600;
                                    background: ${u.role === 'ADMIN' ? 'rgba(251,191,36,0.15)' : 'rgba(0,212,255,0.15)'};
                                    color: ${u.role === 'ADMIN' ? 'var(--warning)' : 'var(--primary)'};
                                    border: 1px solid ${u.role === 'ADMIN' ? 'rgba(251,191,36,0.3)' : 'rgba(0,212,255,0.3)'};
                                ">${u.role || 'CARDHOLDER'}</span>
                            </td>
                            <td style="padding: 0.8rem 1rem; border-bottom: 1px solid var(--glass-border); color: var(--text-dim); font-size: 0.85rem;">${u.enrolled_at ? new Date(u.enrolled_at).toLocaleDateString() : '—'}</td>
                        </tr>
                    `).join('');
                }

                // Transaction History Table
                const txBody = document.getElementById('tx-table-body');
                if (!transactions || transactions.length === 0) {
                    txBody.innerHTML = '<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--text-dim);">No transactions yet</td></tr>';
                } else {
                    txBody.innerHTML = transactions.map((tx, i) => {
                        let decColor = 'var(--text)';
                        if (tx.decision === 'APPROVED') decColor = 'var(--success)';
                        else if (tx.decision.includes('BLOCKED')) decColor = 'var(--error)';
                        else if (tx.decision.includes('REVIEW')) decColor = 'var(--warning)';

                        return `
                        <tr style="animation: fadeIn 0.3s ease ${i * 0.03}s both;">
                            <td style="padding: 0.6rem 1rem; border-bottom: 1px solid var(--glass-border); color: var(--text-dim); font-size: 0.85rem;">${new Date(tx.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
                            <td style="padding: 0.6rem 1rem; border-bottom: 1px solid var(--glass-border); font-weight: 600;">${tx.user_id}</td>
                            <td style="padding: 0.6rem 1rem; border-bottom: 1px solid var(--glass-border); font-family: monospace;">$${tx.amount.toFixed(2)}</td>
                            <td style="padding: 0.6rem 1rem; border-bottom: 1px solid var(--glass-border); font-weight: 600; color: ${decColor}; font-size: 0.8rem;">${tx.decision}</td>
                            <td style="padding: 0.6rem 1rem; border-bottom: 1px solid var(--glass-border); font-family: monospace;">${tx.risk_score ? tx.risk_score.toFixed(4) : '—'}</td>
                            <td style="padding: 0.6rem 1rem; border-bottom: 1px solid var(--glass-border); font-family: monospace;">${tx.face_similarity ? tx.face_similarity.toFixed(4) : '—'}</td>
                        </tr>
                        `;
                    }).join('');
                }

                // System Settings (Optional, leaving static if not fetched)
                // document.getElementById('set-fraud-thresh').textContent = '0.75';
                // document.getElementById('set-review-thresh').textContent = '0.50';
                
            } catch (err) {
                console.error("[API] Error fetching dashboard:", err);
                showToast('Failed to load dashboard data');
                
                // CRITICAL FIX: Replace "Loading..." with Error message
                document.getElementById('users-table-body').innerHTML = `<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--error); font-weight: 600;">Failed to fetch users from backend.</td></tr>`;
                document.getElementById('tx-table-body').innerHTML = `<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--error); font-weight: 600;">Failed to fetch transactions from backend.</td></tr>`;
            }
        }

        // --- Card Validation ---
        function isValidCard(num) {
            let s = num.replace(/\s+/g, '');
            // Simplified check for demo: allow any 13-19 digit number
            return /^\d{13,19}$/.test(s);
        }

        // --- Card Input Formatting ---
        const cardInput = document.getElementById('card-num');
        const cardPreview = document.getElementById('preview-card-num');

        cardInput.addEventListener('input', (e) => {
            let val = e.target.value.replace(/\D/g, '');
            let formatted = val.match(/.{1,4}/g)?.join(' ') || val;
            e.target.value = formatted;
            cardPreview.textContent = formatted || '•••• •••• •••• ••••';
        });

        document.getElementById('card-expiry').addEventListener('input', (e) => {
            let val = e.target.value.replace(/\D/g, '');
            if (val.length > 2) val = val.slice(0, 2) + '/' + val.slice(2, 4);
            e.target.value = val;
            document.getElementById('preview-expiry').textContent = val || 'MM/YY';
        });

        // --- Registration Page Formatting ---
        const regPhone = document.getElementById('reg-phone');
        if (regPhone) {
            regPhone.addEventListener('input', (e) => {
                let val = e.target.value.replace(/[^\d+]/g, ''); // keep + and numbers
                e.target.value = val;
            });
        }

        const regCard = document.getElementById('reg-card-num');
        if (regCard) {
            regCard.addEventListener('input', (e) => {
                let val = e.target.value.replace(/\D/g, '').substring(0, 19);
                let formatted = val.match(/.{1,4}/g)?.join(' ') || val;
                e.target.value = formatted;
            });
        }

        const regExpiry = document.getElementById('reg-card-expiry');
        if (regExpiry) {
            regExpiry.addEventListener('input', (e) => {
                let val = e.target.value.replace(/\D/g, '').substring(0, 4);
                if (val.length > 2) val = val.slice(0, 2) + '/' + val.slice(2, 4);
                e.target.value = val;
            });
        }

        const regCvc = document.getElementById('reg-card-cvc');
        if (regCvc) {
            regCvc.addEventListener('input', (e) => {
                e.target.value = e.target.value.replace(/\D/g, '').substring(0, 3);
            });
        }

        // --- Toast ---
        function showToast(msg, type = "error") {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.style.background = type === "success" ? "var(--success)" : "var(--error)";
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }

        // --- Transaction Logic ---
        async function handleGenOTP() {
            const num = document.getElementById('card-num').value;
            const expiry = document.getElementById('card-expiry').value;

            if (!isValidCard(num)) {
                showToast("Invalid Card Number (must be 13-19 digits)");
                return;
            }

            if (!/^\d{2}\/\d{2}$/.test(expiry)) {
                showToast("Invalid Expiry Date");
                return;
            }

            // Step 1: Validate card against registered data
            const userId = document.getElementById('tx-user-id').value.trim();
            if (!userId) {
                showToast("Please enter your registered User ID");
                return;
            }

            try {
                const validateRes = await fetch(`${API_BASE}/validate-card`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        card_number: num.replace(/\s+/g, '')
                    })
                });

                if (!validateRes.ok) {
                    const err = await validateRes.json();
                    showToast(err.message || "Wrong credentials — card not registered");
                    return;
                }
            } catch (err) {
                showToast("Server Connection Lost");
                return;
            }

            // Step 2: Generate OTP
            try {
                const otpRes = await fetch(`${API_BASE}/generate-otp`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId })
                });

                if (otpRes.ok) {
                    const otpData = await otpRes.json();
                    // Show OTP on screen for testing
                    document.getElementById('otp-display-value').textContent = otpData.otp;
                    document.getElementById('otp-display-box').style.display = 'block';
                    document.getElementById('otp-error').style.display = 'none';

                    document.getElementById('tx-step-1').style.display = 'none';
                    document.getElementById('tx-step-2').style.display = 'block';
                    startOTPTimer();
                    showToast("Card verified! OTP generated.", "success");
                } else {
                    const err = await otpRes.json();
                    showToast(err.message || "Failed to generate OTP");
                }
            } catch (err) {
                showToast("Server Connection Lost");
            }
        }

        function startOTPTimer() {
            let count = 60;
            const el = document.getElementById('otp-timer');
            state.otpTimer = setInterval(() => {
                count--;
                el.textContent = `Expires in ${count}s`;
                if (count <= 0) {
                    clearInterval(state.otpTimer);
                    showToast("OTP Expired");
                    resetTransaction();
                }
            }, 1000);
        }

        async function verifyOTP() {
            const otpInputs = document.querySelectorAll('.otp-input');
            const enteredOTP = Array.from(otpInputs).map(i => i.value).join('');

            if (enteredOTP.length !== 6) {
                showToast("Please enter the complete 6-digit OTP");
                return;
            }

            try {
                const userId = document.getElementById('tx-user-id').value.trim();
                const res = await fetch(`${API_BASE}/verify-otp`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        otp: enteredOTP
                    })
                });

                if (res.ok) {
                    clearInterval(state.otpTimer);
                    document.getElementById('tx-step-2').style.display = 'none';
                    document.getElementById('tx-step-3').style.display = 'block';
                    startFaceAuth(); // Call the new face auth function
                    showToast("OTP verified! Proceed with face authentication.", "success");
                } else {
                    const err = await res.json();
                    document.getElementById('otp-error').textContent = err.message || "Wrong OTP";
                    document.getElementById('otp-error').style.display = 'block';
                    showToast(err.message || "Wrong OTP. Please try again.");
                    // Clear OTP inputs
                    otpInputs.forEach(i => i.value = '');
                    otpInputs[0].focus();
                }
            } catch (err) {
                showToast("Server Connection Lost");
            }
        }

        async function startCamera(videoId) {
            try {
                const video = document.getElementById(videoId);
                const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
                state.videoStream = stream;
                video.srcObject = stream;
            } catch (err) {
                console.error("Camera access failed:", err);
                showToast("Camera Permission Denied");
            }
        }

        async function startFaceAuth() {
            document.getElementById('tx-step-2').style.display = 'none'; // Ensure OTP step is hidden
            document.getElementById('tx-step-3').style.display = 'block'; // Show face auth step

            // Reset liveness state machine (WAITING_FACE -> BLINK_TEST -> SUCCESS)
            state.livenessState = 'WAITING_FACE';
            state.eyesClosedFrames = 0;
            state.hasSeenOpenEyes = false;

            const overlay = document.getElementById('liveness-overlay');
            if (overlay) {
                overlay.textContent = "Please position your face correctly in the frame";
                overlay.style.color = "var(--warning)";
                overlay.style.borderColor = "var(--warning)";
                overlay.style.boxShadow = "0 0 10px rgba(251, 191, 36, 0.2)";
            }

            // Provide the manual capture button as a fallback in case liveness is flaky
            const captureBtn = document.getElementById('capture-btn');
            if (captureBtn) {
                captureBtn.style.display = 'block';
                captureBtn.disabled = false;
                captureBtn.textContent = 'Capture Face (Manual)';
            }

            try {
                const video = document.getElementById('tx-video');

                // Only initialize FaceMesh if it doesn't already exist to prevent duplicate loops
                if (!state.faceMesh) {
                    state.faceMesh = new FaceMesh({
                        locateFile: (file) => {
                            return `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`;
                        }
                    });

                    state.faceMesh.setOptions({
                        maxNumFaces: 1,
                        refineLandmarks: true,
                        minDetectionConfidence: 0.2,
                        minTrackingConfidence: 0.2
                    });
                }

                // Always re-bind the result callback in case it was nullified
                state.faceMesh.onResults(onFaceMeshResults);

                // Only initialize Camera Utils if it doesn't already exist
                if (!state.camera) {
                    state.camera = new Camera(video, {
                        onFrame: async () => {
                            if (state.faceMesh) {
                                await state.faceMesh.send({ image: video });
                            }
                        },
                        width: 640,
                        height: 480
                    });
                }

                // Start tracking loop
                state.camera.start().catch(e => console.error("Camera loop err:", e));

                // Removed 5-second timeout to allow user unlimited time to get into frame

            } catch (err) {
                console.error("Camera access failed:", err);
                showToast("Camera access is required for biometric validation.");
            }
        }

        // --- Liveness Processing Logic (State Machine) --- //
        const LEFT_EYE = [33, 160, 158, 133, 153, 144];
        const RIGHT_EYE = [362, 385, 387, 263, 373, 380];

        const EAR_CLOSED_THRESH = 0.24; // Widened to catch quicker blinks
        const EAR_OPEN_THRESH = 0.26;   // Lowered gap so fast reopens still trigger

        function onFaceMeshResults(results) {
            // Stop processing if already successful
            if (state.livenessState === 'SUCCESS') return;

            const overlay = document.getElementById('liveness-overlay');

            // 1. Check if face is detected
            if (!results.multiFaceLandmarks || results.multiFaceLandmarks.length === 0) {
                if (state.livenessState !== 'WAITING_FACE') {
                    // Reset state if they wander out of frame
                    state.livenessState = 'WAITING_FACE';
                    if (overlay) {
                        overlay.textContent = "Face lost. Please return into the frame.";
                        overlay.style.color = "var(--error)";
                        overlay.style.borderColor = "var(--error)";
                    }
                }
                return;
            }

            const landmarks = results.multiFaceLandmarks[0];

            // Calculate Box Size approximation to ensure they are close enough
            // 234: left cheek, 454: right cheek, 10: top head, 152: bottom chin
            const faceWidth = Math.abs(landmarks[454].x - landmarks[234].x);
            const faceHeight = Math.abs(landmarks[152].y - landmarks[10].y);
            // More forgiving bounds for distance (width > 0.3)
            const isLargeEnough = faceWidth > 0.30 && faceHeight > 0.35;

            // STATE 1: WAITING FACE
            if (state.livenessState === 'WAITING_FACE') {
                if (!isLargeEnough) {
                    if (overlay) overlay.textContent = "Please move closer to the camera";
                } else {
                    // Face is positioned correctly. Advance directly to Blink Test.
                    state.livenessState = 'BLINK_TEST';
                    state.hasSeenOpenEyes = false;
                    state.eyesClosedFrames = 0;
                    if (overlay) {
                        overlay.textContent = "Please BLINK slowly to verify liveness 👀";
                        overlay.style.color = "var(--primary)";
                        overlay.style.borderColor = "var(--primary)";
                        overlay.style.boxShadow = "0 0 10px rgba(0, 212, 255, 0.4)";
                    }
                }
                return; // Wait for next frame
            }

            // STATE 2: STRICT BLINK TEST
            if (state.livenessState === 'BLINK_TEST') {
                if (!isLargeEnough) {
                    if (overlay) {
                        overlay.textContent = "Please move closer to the camera";
                        overlay.style.color = "var(--warning)";
                        overlay.style.borderColor = "var(--warning)";
                        overlay.style.boxShadow = "none";
                    }
                    // Reset blink counter when they move out of frame to prevent partial blinks from carrying over
                    state.hasSeenOpenEyes = false;
                    state.eyesClosedFrames = 0;
                    return;
                } else {
                    // Ensure the blink prompt is restored if they just moved back into frame
                    if (overlay && overlay.textContent !== "Please BLINK slowly to verify liveness 👀") {
                        overlay.textContent = "Please BLINK slowly to verify liveness 👀";
                        overlay.style.color = "var(--primary)";
                        overlay.style.borderColor = "var(--primary)";
                        overlay.style.boxShadow = "0 0 10px rgba(0, 212, 255, 0.4)";
                    }
                }
                const leftEAR = calculateEAR(LEFT_EYE, landmarks);
                const rightEAR = calculateEAR(RIGHT_EYE, landmarks);
                const avgEAR = (leftEAR + rightEAR) / 2.0;

                // Requirement A: Must see fully open eyes first (prevents starting mid-blink or glitch)
                if (!state.hasSeenOpenEyes) {
                    if (avgEAR > EAR_OPEN_THRESH) {
                        state.hasSeenOpenEyes = true;
                    }
                    return;
                }

                // Requirement B: Track the blink closure
                if (avgEAR < EAR_CLOSED_THRESH) {
                    state.eyesClosedFrames++;
                } else if (avgEAR > EAR_OPEN_THRESH && state.eyesClosedFrames >= 1) {
                    // Requirement C: Eyes open again, and were closed for at least 1 frame
                    triggerLivenessSuccess();
                } else {
                    // Reset if they barely flinched (EAR went up but wasn't a solid blink)
                    if (avgEAR > EAR_OPEN_THRESH && state.eyesClosedFrames > 0 && state.eyesClosedFrames < 1) {
                        state.eyesClosedFrames = 0;
                    }
                }
            }
        }

        function triggerLivenessSuccess() {
            state.livenessState = 'SUCCESS';

            const overlay = document.getElementById('liveness-overlay');
            if (overlay) {
                overlay.textContent = "✅ Blink Verified! Capturing face...";
                overlay.style.color = "var(--success)";
                overlay.style.borderColor = "var(--success)";
                overlay.style.boxShadow = "0 0 10px rgba(16, 185, 129, 0.4)";
            }

            // AUTO-CAPTURE: Immediately take the snapshot and submit.
            // This eliminates any window for swapping a photo.
            // Use a tiny delay (200ms) to let the user's eyes fully reopen for the best capture.
            setTimeout(() => {
                simulateFaceAuth();
            }, 200);
        }

        async function handleLivenessFailure() {
            // This function is still here in case we want to re-add timeouts or manual failure triggers
            if (state.livenessState === 'SUCCESS') return;
        }
        function stopCamera() {
            if (state.videoStream) {
                state.videoStream.getTracks().forEach(track => track.stop());
                state.videoStream = null;
            }
            if (state.camera) {
                try { state.camera.stop(); } catch (e) { }
                // Don't nullify the camera, keep it paused for reuse
            }
            if (state.faceMesh) {
                try {
                    state.faceMesh.onResults(() => { }); // Set to empty function to safely stop callbacks
                } catch (e) { }
                // Don't close or nullify FaceMesh, keep it loaded in memory for the next run
            }
            // Ensure any video elements are cleared visually
            document.querySelectorAll('video').forEach(v => {
                v.srcObject = null;
            });
            // Force reset liveness state so it does not carry over
            state.livenessState = 'WAITING_FACE';
            state.eyesClosedFrames = 0;
            state.hasSeenOpenEyes = false;

            // Reset UI Elements so they don't persist next time
            const overlay = document.getElementById('liveness-overlay');
            if (overlay) {
                overlay.textContent = "Initializing Face Check...";
                overlay.style.color = "white";
                overlay.style.borderColor = "rgba(255, 255, 255, 0.1)";
                overlay.style.boxShadow = "none";
            }
            const captureBtn = document.getElementById('capture-btn');
            if (captureBtn) {
                captureBtn.style.display = 'none';
            }
        }

        function captureToBase64(videoId) {
            const video = document.getElementById(videoId);
            const canvas = document.getElementById('hidden-canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL('image/jpeg').split(',')[1]; // Return only B64
        }

        async function simulateFaceAuth() {
            const b64 = captureToBase64('tx-video');
            stopCamera(); // Stop MediaPipe + Camera loops securely

            const overlay = document.getElementById('liveness-overlay');
            if (overlay) overlay.textContent = "Face Snapshot Taken! Analyzing Identity...";
            const scanLine = document.getElementById('tx-scan-line');
            if (scanLine) scanLine.style.display = 'block';

            try {
                const userId = document.getElementById('tx-user-id').value.trim();
                console.log(`[API] Sending transaction to: ${API_BASE}/transaction`);
                const res = await fetch(`${API_BASE}/transaction`, {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify({
                        user_id: userId,
                        card_number: document.getElementById('card-num').value.replace(/\s+/g, ''),
                        amount: 599.00,
                        merchant_category: "electronics",
                        face_image_b64: b64
                    })
                });

                const result = await res.json();
                console.log("[API] Response Status:", res.status);
                console.log("[API] Response Body:", result);

                if (!res.ok) {
                    // Handle FastAPI 422 (Validation) or 400 (Business Logic) errors
                    const errMsg = result.message || result.detail || "Transaction Error";
                    showToast(errMsg, "error");
                    if (scanLine) scanLine.style.display = 'none';
                    return;
                }

                if (result.decision === "APPROVED") {
                    confetti({
                        particleCount: 150,
                        spread: 70,
                        origin: { y: 0.6 },
                        colors: ['#00d4ff', '#10b981', '#ffffff']
                    });
                    document.getElementById('tx-step-3').style.display = 'none';
                    document.getElementById('tx-step-4').style.display = 'block';
                    document.getElementById('tx-success-id').textContent = `TxID: ${result.tx_id}`;
                    stopCamera();
                } else if (result.decision === "BLOCKED_BIOMETRIC_FAILURE") {
                    document.getElementById('tx-step-3').style.display = 'none';
                    document.getElementById('tx-step-fraud').style.display = 'block';
                    stopCamera();
                } else if (result.decision === "HELD_FOR_REVIEW") {
                    showToast("Transaction Held for Review", "warning");
                } else {
                    showToast(`Transaction Blocked: ${result.message || "Fraud Detected"}`);
                }
            } catch (err) {
                // Check if the error is from the API (card mismatch, etc.)
                if (err.message) {
                    showToast(err.message);
                } else {
                    showToast("Connection to Fraud Engine Failed");
                }
            }
        }

        function resetTransaction() {
            stopCamera(); // Ensure camera/FaceMesh are killed before resetting UI
            document.getElementById('tx-step-1').style.display = 'block';
            document.getElementById('tx-step-2').style.display = 'none';
            document.getElementById('tx-step-3').style.display = 'none';
            document.getElementById('tx-step-4').style.display = 'none';
            document.getElementById('tx-step-fraud').style.display = 'none';
            document.getElementById('otp-display-box').style.display = 'none';
            document.getElementById('otp-error').style.display = 'none';
            document.querySelectorAll('.otp-input').forEach(i => i.value = '');
            clearInterval(state.otpTimer);
        }

        // --- Registration Logic ---
        function nextRegStep(step) {
            if (step === 3) {
                const cardNum = document.getElementById('reg-card-num').value;
                if (!isValidCard(cardNum)) {
                    showToast("Invalid Card Number (must be 13-19 digits)");
                    return;
                }
            }

            document.querySelectorAll('[id^="reg-step-"]').forEach(s => s.style.display = 'none');
            document.getElementById(`reg-step-${step}`).style.display = 'block';

            document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
            for (let i = 1; i <= step; i++) {
                document.getElementById(`step-dot-${i}`)?.classList.add('active');
            }

            if (step === 3) startCamera('reg-video');
            else if (step < 3) stopCamera();
        }

        async function captureFaceShot() {
            state.faceShots++;
            document.getElementById(`shot-${state.faceShots}`).style.background = 'var(--primary)';

            // Capture the current frame as Base64 for enrollment
            state.lastFaceB64 = captureToBase64('reg-video');

            if (state.faceShots >= 3) {
                const btn = document.getElementById('reg-capture-btn');
                btn.disabled = true;
                btn.textContent = "Finalizing Enrollment...";

                const userId = document.getElementById('reg-user-id').value || "user_" + Date.now();
                const cardNum = document.getElementById('reg-card-num').value.replace(/\s+/g, '') || "0000";
                const emailAdd = document.getElementById('reg-email').value.trim() || null;

                try {
                    const res = await fetch(`${API_BASE}/enroll`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            user_id: userId,
                            card_number: cardNum,
                            email: emailAdd,
                            face_image_b64: state.lastFaceB64
                        })
                    });

                    if (res.ok) {
                        nextRegStep(4);
                        stopCamera();
                    } else {
                        const data = await res.json();
                        showToast(data.message || data.detail || "Enrollment Failed");
                    }
                } catch (err) {
                    showToast("Database Connectivity Error");
                } finally {
                    btn.disabled = false;
                    btn.textContent = "Capture Shot";
                }
            } else {
                showToast(`Captured Shot ${state.faceShots}/3`, "success");
            }
        }

        function resetRegistration() {
            state.faceShots = 0;
            document.querySelectorAll('.shot-dot').forEach(d => d.style.background = 'var(--glass-border)');
            document.getElementById('reg-capture-btn').disabled = false;
            document.getElementById('reg-capture-btn').textContent = "Capture Shot";
            nextRegStep(1);
        }

        // --- OTP Input Auto Advance & Backspace ---
        const otpInputs = document.querySelectorAll('.otp-input');
        otpInputs.forEach((input, idx) => {
            // Auto advance on input
            input.addEventListener('input', (e) => {
                if (e.target.value.length === 1 && idx < otpInputs.length - 1) {
                    otpInputs[idx + 1].focus();
                }
            });
            // Handle Backspace
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !e.target.value && idx > 0) {
                    otpInputs[idx - 1].focus();
                }
            });
        });

        // --- Backend Integration Reference (How to connect to FraudDetection_Project backend) ---
        /*
        Example Fetch Call:
        async function verifyFaceAgainstBackend(imageBase64) {
            const response = await fetch('http://localhost:8000/transaction', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + st.token },
                body: JSON.stringify({
                    user_id: "current_user",
                    face_image_b64: imageBase64,
                    amount: 599.00,
                    // ... other required tx features
                })
            });
            return await response.json();
        }
        */