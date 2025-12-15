"""
Tariff Stacking API Views.
Clean form-based UI for tariff calculation.
"""

import uuid
from flask import Blueprint, request, jsonify, render_template_string
from app.chat.graphs.stacking_rag import StackingRAG

bp = Blueprint("tariff", __name__)

# Store active sessions
_sessions = {}


@bp.route("/", methods=["GET"])
def calculator_page():
    """Serve the tariff calculator UI."""
    return render_template_string(CALCULATOR_HTML)


@bp.route("/tariff/calculate", methods=["POST"])
def calculate_tariff():
    """Calculate tariff stacking."""
    try:
        data = request.json or {}

        hts_code = data.get("hts_code", "").strip()
        country = data.get("country", "").strip()
        product_value = float(data.get("product_value") or 10000)
        product_description = data.get("product_description", "").strip() or f"Product ({hts_code})"
        materials = data.get("materials")
        session_id = data.get("session_id")

        if not hts_code or not country:
            return jsonify({"success": False, "error": "HTS code and country are required"}), 400

        # Continue with materials if session exists
        if session_id and session_id in _sessions:
            rag = _sessions[session_id]
            result = rag.continue_with_materials(materials or {})
            del _sessions[session_id]
        else:
            # New calculation
            session_id = str(uuid.uuid4())
            rag = StackingRAG(conversation_id=session_id)

            result = rag.calculate_stacking(
                hts_code=hts_code,
                country=country,
                product_description=product_description,
                product_value=product_value,
                materials=materials
            )

            # Check if we need materials
            if result.get("awaiting_user_input"):
                _sessions[session_id] = rag
                return jsonify({
                    "success": True,
                    "session_id": session_id,
                    "needs_materials": True,
                    "message": "This HTS code may contain Section 232 metals. Please enter the material values.",
                    "entries": [],
                    "total_duty": None
                })

        # Return results
        total_duty = result.get("total_duty") or {}
        return jsonify({
            "success": True,
            "session_id": None,
            "needs_materials": False,
            # Product context for display
            "hts_code": hts_code,
            "country": country,
            "product_description": product_description,
            "product_value": product_value,
            "materials": materials or {},
            # Calculation results
            "entries": result.get("entries", []),
            "total_duty": total_duty,
            "effective_rate": total_duty.get("effective_rate", 0)
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


CALCULATOR_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tariff Stacker</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8fafc;
            min-height: 100vh;
            color: #1e293b;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        .header {
            text-align: center;
            margin-bottom: 40px;
        }
        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 8px;
        }
        .header p {
            color: #64748b;
            font-size: 1.1rem;
        }
        .refresh-btn {
            position: absolute;
            top: 16px;
            right: 16px;
            padding: 8px 16px;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            cursor: pointer;
            color: #64748b;
            transition: all 0.2s;
        }
        .refresh-btn:hover {
            background: #e2e8f0;
            color: #1e293b;
        }
        .card {
            background: white;
            border-radius: 16px;
            padding: 32px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
            margin-bottom: 24px;
        }
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }
        @media (max-width: 768px) {
            .form-row { grid-template-columns: 1fr; }
        }
        .form-group label {
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            color: #374151;
        }
        .form-group input, .form-group select {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e2e8f0;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.2s;
        }
        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #6366f1;
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
        }
        .form-group .hint {
            font-size: 12px;
            color: #94a3b8;
            margin-top: 4px;
        }
        .materials-section {
            display: none;
            background: #fef3c7;
            border: 2px solid #fbbf24;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }
        .materials-section.show { display: block; }
        .materials-section h3 {
            color: #92400e;
            margin-bottom: 8px;
            font-size: 1rem;
        }
        .materials-section p {
            color: #a16207;
            font-size: 14px;
            margin-bottom: 16px;
        }
        .materials-row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 16px;
        }
        button {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px -5px rgba(99, 102, 241, 0.4);
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .result {
            display: none;
        }
        .result.show { display: block; }
        .result-summary {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            padding: 24px;
            border-radius: 12px;
            text-align: center;
            margin-bottom: 24px;
        }
        .result-summary h2 {
            font-size: 2.5rem;
            margin-bottom: 4px;
        }
        .result-summary p {
            opacity: 0.9;
            font-size: 1.1rem;
        }
        .entries-title {
            font-weight: 600;
            color: #374151;
            margin-bottom: 16px;
            font-size: 1.1rem;
        }
        .entry {
            background: #f8fafc;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            border-left: 4px solid #6366f1;
        }
        .entry-header {
            display: flex;
            justify-content: space-between;
            font-weight: 600;
            margin-bottom: 12px;
            color: #1e293b;
        }
        .entry-value {
            color: #6366f1;
        }
        .stack-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid #e2e8f0;
            font-size: 14px;
        }
        .stack-item:last-child { border-bottom: none; }
        .stack-code {
            font-family: 'SF Mono', Monaco, monospace;
            background: #e2e8f0;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
            margin-right: 8px;
        }
        .stack-action {
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .stack-action.apply { background: #dbeafe; color: #1d4ed8; }
        .stack-action.claim { background: #dcfce7; color: #166534; }
        .stack-action.disclaim { background: #f1f5f9; color: #64748b; }
        .stack-action.paid { background: #fef3c7; color: #92400e; }
        .stack-action.exempt { background: #d1fae5; color: #065f46; }
        .loading {
            display: none;
            text-align: center;
            padding: 40px;
        }
        .loading.show { display: block; }
        .spinner {
            width: 48px;
            height: 48px;
            border: 4px solid #e2e8f0;
            border-top-color: #6366f1;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .error {
            display: none;
            background: #fef2f2;
            color: #dc2626;
            padding: 16px;
            border-radius: 10px;
            margin-bottom: 16px;
        }
        .error.show { display: block; }
        .new-calc-btn {
            background: #64748b;
            margin-top: 16px;
        }
        .toggle-group {
            display: flex;
            gap: 0;
            border: 2px solid #e2e8f0;
            border-radius: 10px;
            overflow: hidden;
            width: fit-content;
        }
        .toggle-btn {
            width: auto;
            padding: 10px 20px;
            background: #f8fafc;
            border: none;
            border-radius: 0;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            color: #64748b;
            transition: all 0.2s;
        }
        .toggle-btn:hover {
            background: #f1f5f9;
            transform: none;
            box-shadow: none;
        }
        .toggle-btn.active {
            background: #6366f1;
            color: white;
        }
        .toggle-btn.active:hover {
            background: #5855e0;
        }
        .product-summary {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }
        .product-summary h3 {
            margin: 0 0 16px 0;
            font-size: 13px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .product-info {
            display: grid;
            gap: 10px;
        }
        .info-row {
            display: flex;
            gap: 12px;
        }
        .info-row .label {
            color: #64748b;
            min-width: 110px;
            font-size: 14px;
        }
        .info-row .value {
            font-weight: 500;
            color: #1e293b;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container" style="position: relative;">
        <button class="refresh-btn" onclick="refreshPage()">⟳ Reset</button>
        <div class="header">
            <h1>Tariff Stacker</h1>
            <p>Enter your HTS code and country of origin to calculate tariffs and prepare your ACE entry.</p>
        </div>

        <div class="card" id="formCard">
            <form id="tariffForm">
                <div class="form-row">
                    <div class="form-group">
                        <label>HTS Code</label>
                        <input type="text" id="htsCode" placeholder="8544.42.9090" required>
                        <div class="hint">10-digit Harmonized Tariff Schedule code</div>
                    </div>
                    <div class="form-group">
                        <label>Product Description (Optional)</label>
                        <input type="text" id="productDescription" placeholder="E.g., USB-C cable with braided jacket">
                        <div class="hint">Makes results easier to reference</div>
                    </div>
                    <div class="form-group">
                        <label>Country of Origin</label>
                        <select id="country" required>
                            <option value="">Select a country</option>
                            <optgroup label="IEEPA Fentanyl Countries">
                                <option value="China">China (CN)</option>
                                <option value="Hong Kong">Hong Kong (HK)</option>
                                <option value="Macau">Macau (MO)</option>
                            </optgroup>
                            <optgroup label="IEEPA Reciprocal Countries">
                                <option value="UK">United Kingdom (UK)</option>
                                <option value="France">France (FR)</option>
                                <option value="Italy">Italy (IT)</option>
                                <option value="Spain">Spain (ES)</option>
                                <option value="Netherlands">Netherlands (NL)</option>
                                <option value="Belgium">Belgium (BE)</option>
                                <option value="Switzerland">Switzerland (CH)</option>
                                <option value="Austria">Austria (AT)</option>
                                <option value="Ireland">Ireland (IE)</option>
                                <option value="Poland">Poland (PL)</option>
                                <option value="Sweden">Sweden (SE)</option>
                                <option value="Denmark">Denmark (DK)</option>
                                <option value="Norway">Norway (NO)</option>
                                <option value="Finland">Finland (FI)</option>
                                <option value="Japan">Japan (JP)</option>
                                <option value="South Korea">South Korea (KR)</option>
                                <option value="Taiwan">Taiwan (TW)</option>
                                <option value="Singapore">Singapore (SG)</option>
                                <option value="Thailand">Thailand (TH)</option>
                                <option value="Malaysia">Malaysia (MY)</option>
                                <option value="Indonesia">Indonesia (ID)</option>
                                <option value="Vietnam">Vietnam (VN)</option>
                                <option value="Philippines">Philippines (PH)</option>
                                <option value="India">India (IN)</option>
                                <option value="Australia">Australia (AU)</option>
                                <option value="New Zealand">New Zealand (NZ)</option>
                                <option value="Brazil">Brazil (BR)</option>
                                <option value="Argentina">Argentina (AR)</option>
                            </optgroup>
                            <optgroup label="232 Only (No IEEPA)">
                                <option value="Germany">Germany (DE)</option>
                                <option value="Canada">Canada (CA)</option>
                                <option value="Mexico">Mexico (MX)</option>
                            </optgroup>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Product Value (USD)</label>
                        <input type="number" id="productValue" value="10000" min="1" required>
                        <div class="hint">Total declared value</div>
                    </div>
                </div>

                <div class="materials-section" id="materialsSection">
                    <h3>Section 232 Metals Detected</h3>
                    <p>This product may contain metals subject to Section 232 duties. Enter the metal content:</p>
                    <div class="form-group" style="margin-bottom: 16px;">
                        <label>Input Type</label>
                        <div class="toggle-group">
                            <button type="button" class="toggle-btn active" id="pctToggle" onclick="setMaterialsMode('percentage')">Percentage (%)</button>
                            <button type="button" class="toggle-btn" id="valToggle" onclick="setMaterialsMode('value')">Dollar Value ($)</button>
                        </div>
                        <div class="hint" id="materialsHint">Enter as percentage of product value (e.g., 30 = 30%)</div>
                    </div>
                    <div class="materials-row">
                        <div class="form-group">
                            <label id="copperLabel">Copper (%)</label>
                            <input type="number" id="copperValue" placeholder="0" min="0" step="any">
                        </div>
                        <div class="form-group">
                            <label id="steelLabel">Steel (%)</label>
                            <input type="number" id="steelValue" placeholder="0" min="0" step="any">
                        </div>
                        <div class="form-group">
                            <label id="aluminumLabel">Aluminum (%)</label>
                            <input type="number" id="aluminumValue" placeholder="0" min="0" step="any">
                        </div>
                    </div>
                </div>

                <div class="error" id="error"></div>

                <button type="submit" id="submitBtn">Calculate Tariffs</button>
            </form>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p>Calculating tariffs...</p>
            </div>
        </div>

        <div class="card result" id="result">
            <div class="product-summary" id="productSummary">
                <!-- Filled by JavaScript -->
            </div>

            <div class="result-summary">
                <h2 id="totalDuty">$0.00</h2>
                <p><span id="effectiveRate">0%</span> effective duty rate</p>
            </div>

            <div class="entries-title">ACE Entry Slices</div>
            <div id="entries"></div>

            <button class="new-calc-btn" onclick="resetForm()">New Calculation</button>
        </div>
    </div>

    <script>
        let sessionId = null;
        let lastHtsCode = '';
        let lastCountry = '';
        let materialsMode = 'percentage';  // 'percentage' or 'value'

        function setMaterialsMode(mode) {
            materialsMode = mode;
            const isPercentage = mode === 'percentage';

            // Update toggle buttons
            document.getElementById('pctToggle').classList.toggle('active', isPercentage);
            document.getElementById('valToggle').classList.toggle('active', !isPercentage);

            // Update labels
            document.getElementById('copperLabel').textContent = isPercentage ? 'Copper (%)' : 'Copper ($)';
            document.getElementById('steelLabel').textContent = isPercentage ? 'Steel (%)' : 'Steel ($)';
            document.getElementById('aluminumLabel').textContent = isPercentage ? 'Aluminum (%)' : 'Aluminum ($)';

            // Update hint
            document.getElementById('materialsHint').textContent = isPercentage
                ? 'Enter as percentage of product value (e.g., 30 = 30%)'
                : 'Enter as dollar value (e.g., 3000 = $3,000)';
        }

        document.getElementById('tariffForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await calculate();
        });

        // Clear session when inputs change (new calculation)
        document.getElementById('htsCode').addEventListener('change', clearSessionIfInputChanged);
        document.getElementById('country').addEventListener('change', clearSessionIfInputChanged);

        function clearSessionIfInputChanged() {
            const currentHts = document.getElementById('htsCode').value.trim();
            const currentCountry = document.getElementById('country').value;

            if (currentHts !== lastHtsCode || currentCountry !== lastCountry) {
                sessionId = null;
                document.getElementById('materialsSection').classList.remove('show');
                document.getElementById('submitBtn').textContent = 'Calculate Tariffs';
            }
        }

        function refreshPage() {
            sessionId = null;
            lastHtsCode = '';
            lastCountry = '';
            materialsMode = 'percentage';
            document.getElementById('htsCode').value = '';
            document.getElementById('productDescription').value = '';
            document.getElementById('country').value = '';
            document.getElementById('productValue').value = '10000';
            document.getElementById('copperValue').value = '';
            document.getElementById('steelValue').value = '';
            document.getElementById('aluminumValue').value = '';
            document.getElementById('materialsSection').classList.remove('show');
            document.getElementById('submitBtn').textContent = 'Calculate Tariffs';
            document.getElementById('formCard').style.display = 'block';
            document.getElementById('result').classList.remove('show');
            document.getElementById('error').classList.remove('show');
            // Reset toggle to percentage
            setMaterialsMode('percentage');
        }

        async function calculate() {
            const htsCode = document.getElementById('htsCode').value.trim();
            const country = document.getElementById('country').value;
            const productValue = parseFloat(document.getElementById('productValue').value) || 10000;

            // Clear session if inputs changed (new calculation)
            if (htsCode !== lastHtsCode || country !== lastCountry) {
                sessionId = null;
            }

            const productDescription = document.getElementById('productDescription').value.trim();
            const data = {
                hts_code: htsCode,
                country: country,
                product_value: productValue,
                product_description: productDescription || `Product (${htsCode})`,
                session_id: sessionId
            };

            // Add materials if visible (continuing a session)
            if (document.getElementById('materialsSection').classList.contains('show') && sessionId) {
                const materials = {};
                let copper = parseFloat(document.getElementById('copperValue').value) || 0;
                let steel = parseFloat(document.getElementById('steelValue').value) || 0;
                let aluminum = parseFloat(document.getElementById('aluminumValue').value) || 0;

                // Convert percentage to value if in percentage mode
                if (materialsMode === 'percentage') {
                    copper = copper > 0 ? (copper / 100) * productValue : 0;
                    steel = steel > 0 ? (steel / 100) * productValue : 0;
                    aluminum = aluminum > 0 ? (aluminum / 100) * productValue : 0;
                }

                if (copper > 0) materials.copper = copper;
                if (steel > 0) materials.steel = steel;
                if (aluminum > 0) materials.aluminum = aluminum;
                if (Object.keys(materials).length > 0) {
                    data.materials = materials;
                }
            }

            // Show loading
            document.getElementById('loading').classList.add('show');
            document.getElementById('error').classList.remove('show');
            document.getElementById('submitBtn').disabled = true;

            try {
                const response = await fetch('/tariff/calculate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await response.json();
                document.getElementById('loading').classList.remove('show');
                document.getElementById('submitBtn').disabled = false;

                if (!result.success) {
                    document.getElementById('error').textContent = result.error;
                    document.getElementById('error').classList.add('show');
                    return;
                }

                if (result.needs_materials) {
                    sessionId = result.session_id;
                    lastHtsCode = htsCode;
                    lastCountry = country;
                    document.getElementById('materialsSection').classList.add('show');
                    document.getElementById('submitBtn').textContent = 'Calculate with Materials';
                    return;
                }

                // Show results - save inputs and clear session
                sessionId = null;
                lastHtsCode = htsCode;
                lastCountry = country;
                displayResults(result);

            } catch (err) {
                document.getElementById('loading').classList.remove('show');
                document.getElementById('submitBtn').disabled = false;
                document.getElementById('error').textContent = 'Error: ' + err.message;
                document.getElementById('error').classList.add('show');
            }
        }

        function displayResults(result) {
            const totalDuty = result.total_duty?.total_duty_amount || 0;
            const effectiveRate = (result.effective_rate || 0) * 100;

            // Format materials for display
            let compositionText = 'None specified';
            if (result.materials && Object.keys(result.materials).length > 0) {
                compositionText = Object.entries(result.materials)
                    .filter(([_, val]) => val > 0)
                    .map(([mat, val]) => {
                        const pct = ((val / result.product_value) * 100).toFixed(0);
                        return `${mat.charAt(0).toUpperCase() + mat.slice(1)} ${pct}% ($${val.toLocaleString()})`;
                    })
                    .join(', ') || 'None specified';
            }

            // Populate product summary
            document.getElementById('productSummary').innerHTML = `
                <h3>Product</h3>
                <div class="product-info">
                    <div class="info-row">
                        <span class="label">Name:</span>
                        <span class="value">${result.product_description || 'Not specified'}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">HTS Code:</span>
                        <span class="value">${result.hts_code || ''}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Country:</span>
                        <span class="value">${result.country || ''}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Value:</span>
                        <span class="value">$${(result.product_value || 0).toLocaleString()}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Composition:</span>
                        <span class="value">${compositionText}</span>
                    </div>
                </div>
            `;

            document.getElementById('totalDuty').textContent = '$' + totalDuty.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById('effectiveRate').textContent = effectiveRate.toFixed(1) + '%';

            const entriesHtml = (result.entries || []).map(entry => {
                const stackHtml = (entry.stack || []).map(line => {
                    const actionClass = line.action.toLowerCase();
                    const rate = line.duty_rate ? (line.duty_rate * 100).toFixed(0) + '%' : '0%';
                    return `
                        <div class="stack-item">
                            <span>
                                <span class="stack-code">${line.chapter_99_code}</span>
                                ${line.program.substring(0, 25)}
                            </span>
                            <span>
                                <span style="color: #64748b; margin-right: 8px;">${rate}</span>
                                <span class="stack-action ${actionClass}">${line.action}</span>
                            </span>
                        </div>
                    `;
                }).join('');

                return `
                    <div class="entry">
                        <div class="entry-header">
                            <span>${entry.entry_id}</span>
                            <span class="entry-value">$${entry.line_value.toLocaleString()}</span>
                        </div>
                        ${stackHtml}
                    </div>
                `;
            }).join('');

            document.getElementById('entries').innerHTML = entriesHtml;
            document.getElementById('formCard').style.display = 'none';
            document.getElementById('result').classList.add('show');
        }

        function resetForm() {
            sessionId = null;
            document.getElementById('materialsSection').classList.remove('show');
            document.getElementById('submitBtn').textContent = 'Calculate Tariffs';
            document.getElementById('formCard').style.display = 'block';
            document.getElementById('result').classList.remove('show');
            document.getElementById('copperValue').value = '';
            document.getElementById('steelValue').value = '';
            document.getElementById('aluminumValue').value = '';
        }
    </script>
</body>
</html>
'''
