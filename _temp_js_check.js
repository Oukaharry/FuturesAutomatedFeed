// Extracted JS for syntax check

        // --- DEBUGGER ---
        function debugLog(msg, type='info') {
            if (type === 'error') console.error(msg);
            // else console.log(msg);
        }

        window.onerror = function(msg, url, lineNo, columnNo, error) {
            console.error(`ERROR: ${msg} (Line ${lineNo})`);
            return false;
        };
        
        // Escape Key Listener
        document.addEventListener('keydown', function(event) {
            if (event.key === "Escape") {
                debugLog("ESC key pressed. Attempting to close modal.");
                if (document.getElementById('editUserModal').style.display !== 'none') closeEditUserModal();
                else if (window.closeUserListModal) window.closeUserListModal();
            }
        });

        debugLog("Script initialization started...");

        // API Base Functions to replace inline calls
        async function apiCall(url, data) {
            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                const result = await res.json();
                if (result.status === 'success') {
                    // alert('Success'); // Removed intrusive alerts
                    loadData(); // Reload UI
                    
                    // Clear inputs
                    const inputs = document.querySelectorAll('input');
                    inputs.forEach(input => input.value = '');
                } else {
                    alert('Error: ' + result.message);
                }
            } catch (err) {
                console.error(err);
                alert('Connection Error');
            }
        }

        // Functions exposed to HTML onclicks
        function addAdmin() {
            const name = document.getElementById('new-admin-name').value;
            const email = document.getElementById('new-admin-email').value;
            if(!name) return alert('Name required');
            apiCall('/api/admin/create_user', { username: name, user_type: 'admin', email: email });
        }
        function addTrader() {
            const admin = document.getElementById('admin-select-trader').value;
            const name = document.getElementById('new-trader-name').value;
            const email = document.getElementById('new-trader-email').value;
            if(!admin || !name) return alert('Admin and Name required');
            apiCall('/api/admin/create_user', { username: name, user_type: 'trader', parent_user: admin, email: email });
        }
        function addClient() {
            const admin = document.getElementById('admin-select-client').value;
            const trader = document.getElementById('trader-select-client').value;
            const name = document.getElementById('new-client-name').value;
            const emailInput = document.getElementById('new-client-email');
            const email = emailInput ? emailInput.value : '';
            
            if(!trader || !name) return alert('Trader and Name required');
            apiCall('/api/admin/create_user', { username: name, user_type: 'client', parent_user: trader, email: email });
        }
        
        // Modal Logic
        let renderInterval = null; // To control the chunked rendering loop
        let renderTimeout = null;
        let currentRenderId = 0;

        // Simplified Synchronous Version
        function openUserListModal(type) {
             debugLog(`openUserListModal called for: ${type}`);
             
             try {
                const modal = document.getElementById('userListModal');
                if(!modal) { debugLog("FATAL: #userListModal missing", 'error'); return; }
                
                // Show modal immediately: ensure display AND opacity are set to override CSS
                modal.style.display = 'block';
                modal.style.opacity = '1'; 
                modal.classList.add('show'); // Just in case CSS relies on this class
                
                document.getElementById('modalTitle').textContent = type.toUpperCase() + 'S';
                
                const tbody = document.getElementById('userListBody');
                tbody.innerHTML = '';
                
                // Synchronous generation for max reliability
                debugLog("Generating rows synchronously...");
                
                const rows = [];
                // Gather Data
                try {
                    if (type === 'admin') {
                        if(hierarchyData.admins) {
                            Object.entries(hierarchyData.admins).forEach(([name, data]) => {
                                rows.push({ name, email: data.email, parent: null, url: '#', type: 'admin' });
                            });
                        }
                    } else if (type === 'trader') {
                        if(hierarchyData.admins) {
                            Object.entries(hierarchyData.admins).forEach(([adminName, adminData]) => {
                                Object.entries(adminData.traders || {}).forEach(([traderName, traderData]) => {
                                    let email = (traderData && traderData.email) ? traderData.email : '';
                                    rows.push({ name: traderName, email: email, parent: adminName, url: '#', type: 'trader', admin: adminName });
                                });
                            });
                        }
                    } else if (type === 'client') {
                        if(hierarchyData.admins) {
                            Object.entries(hierarchyData.admins).forEach(([adminName, adminData]) => {
                                const traders = adminData.traders || {};
                                Object.entries(traders).forEach(([traderName, traderData]) => {
                                    let clients = [];
                                    if (Array.isArray(traderData)) clients = traderData;
                                    else if (traderData && traderData.clients) clients = traderData.clients;
                                    
                                    if(Array.isArray(clients)){
                                        clients.forEach(client => {
                                            if (!client) return;
                                            const cName = (typeof client === 'object') ? client.name : client;
                                            const cEmail = (typeof client === 'object') ? client.email : '';
                                            const cCat = (typeof client === 'object') ? (client.category || client.profile || 'Private') : 'Private';
                                            rows.push({ 
                                                name: cName || 'Unknown', 
                                                email: cEmail, 
                                                parent: `${traderName} (${adminName})`,
                                                url: '/dashboard/' + cName,
                                                type: 'client',
                                                admin: adminName,
                                                trader: traderName,
                                                category: cCat
                                            });
                                        });
                                    }
                                });
                            });
                        }
                    }
                } catch(e) { debugLog("Data gather error: " + e.message, 'error'); }

                debugLog(`Got ${rows.length} rows.`);
                
                // Handle Columns
                const colParentHeader = document.getElementById('col-parent');
                if (type === 'admin') colParentHeader.style.display = 'none';
                else {
                    colParentHeader.style.display = 'table-cell';
                    colParentHeader.textContent = (type==='client') ? 'Trader/Admin' : 'Admin';
                }

                if (rows.length === 0) {
                     tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:white;">No records found</td></tr>';
                } else {
                     // Build HTML String
                     let html = '';
                     for(let i=0; i<rows.length; i++) {
                         const r = rows[i];
                         const safeName = r.name.replace(/'/g, "\\'");
                         const safeEmail = (r.email||'').replace(/'/g, "\\'");
                         
                         let btns = '';
                         // Common button styles
                         const delStyle = "color:#ef4444; border:1px solid #7f1d1d; background:rgba(127,29,29,0.2); cursor:pointer; padding:4px 8px; border-radius:4px; font-weight:bold; margin-right:5px;";
                         const editStyle = "color:#fbbf24; border:1px solid #78350f; background:rgba(120,53,15,0.2); cursor:pointer; padding:4px 8px; border-radius:4px; font-weight:bold;";

                         if(type === 'client') {
                             btns += `<a href="${r.url}" style="color:#fbbf24; text-decoration:none; margin-right:10px; font-weight:bold;">Dash</a>`;
                             btns += `<button onclick="deleteUser('client', '${safeName}', '${r.admin}', '${r.trader}')" style="${delStyle}">Del</button>`;
                             btns += `<button onclick="openEditUserModal('client', '${safeName}', '${safeEmail}', '${r.admin}', '${r.trader}', '${r.category || ''}')" style="${editStyle}">Edit</button>`;
                         } else if (type === 'trader') {
                             btns += `<button onclick="deleteUser('trader', '${safeName}', '${r.admin}')" style="${delStyle}">Del</button>`;
                             btns += `<button onclick="openEditUserModal('trader', '${safeName}', '${safeEmail}', '${r.admin}')" style="${editStyle}">Edit</button>`;
                         } else {
                             btns += `<button onclick="deleteUser('admin', '${safeName}')" style="${delStyle}">Del</button>`;
                             btns += `<button onclick="openEditUserModal('admin', '${safeName}', '${safeEmail}')" style="${editStyle}">Edit</button>`;
                         }
                         // Reset Password button (all user types)
                         const resetStyle = "color:#60a5fa; border:1px solid #1e3a5f; background:rgba(30,58,95,0.3); cursor:pointer; padding:4px 8px; border-radius:4px; font-weight:bold; margin-left:5px;";
                         btns += `<button onclick="resetUserPassword('${safeName}')" style="${resetStyle}" title="Reset login password">🔑</button>`;

                         let parentCol = (type !== 'admin') ? `<td style="padding:10px; color:#cbd5e1;">${r.parent || '-'}</td>` : '';
                         
                         // Create clickable email span
                         const emailDisplay = (r.email) ? r.email : '<span style="color:#64748b; font-style:italic;">No Email</span>';
                         const editArgs = (type==='client') 
                            ? `'client', '${safeName}', '${safeEmail}', '${r.admin}', '${r.trader}', '${r.category || ''}'` 
                            : (type==='trader') 
                                ? `'trader', '${safeName}', '${safeEmail}', '${r.admin}'` 
                                : `'admin', '${safeName}', '${safeEmail}'`;

                         html += `
                            <tr style="border-bottom: 1px solid #334155;">
                                <td style="padding:10px; color:#f1f5f9;">
                                    <div style="font-weight:bold; font-size:1rem;">${r.name}</div>
                                    <div style="font-size:0.85rem; color:#94a3b8; margin-top:2px; cursor:pointer;" 
                                         title="Click to Edit Email"
                                         onclick="openEditUserModal(${editArgs})">
                                        ${emailDisplay} <i class="fas fa-pencil-alt" style="font-size:0.7rem; opacity:0.5; margin-left:4px;"></i>
                                    </div>
                                </td>
                                ${parentCol}
                                <td style="padding:10px; text-align:right;">${btns}</td>
                            </tr>
                         `;
                     }
                     tbody.innerHTML = html;
                }
                
                debugLog("Render Complete.");

             } catch(err) {
                 debugLog("FATAL ERROR: " + err.message, 'error');
                 alert("Error: " + err.message);
             }
        }
        
        function closeUserListModal() {
            const m = document.getElementById('userListModal');
            if(m) m.style.display = 'none';
        }



        // --- Edit / Delete User Logic ---
        
        function openEditUserModal(type, name, email, parent1, parent2, extra) {
             if(event) event.stopPropagation();
             
             // Clean up escaped values
             const cleanName = (name || '').replace(/\\'/g, "'");
             const cleanEmail = (email && email !== 'undefined' && email !== 'null') ? email.replace(/\\'/g, "'") : '';
             const cleanCategory = (extra && extra !== 'undefined' && extra !== 'null') ? extra : 'Private';
             
             // Populate modal fields
             document.getElementById('editModalTitle').textContent = 'Edit ' + type.charAt(0).toUpperCase() + type.slice(1);
             document.getElementById('editUserName').value = cleanName;
             document.getElementById('editUserEmail').value = cleanEmail;
             document.getElementById('editUserType').value = type;
             document.getElementById('editUserAdmin').value = parent1 || '';
             document.getElementById('editUserTrader').value = parent2 || '';
             document.getElementById('editUserOriginalName').value = cleanName; // Store original for rename detection
             
             // Show category dropdown only for clients
             const catGroup = document.getElementById('editClientCategoryGroup');
             if (type === 'client') {
                 catGroup.style.display = 'block';
                 document.getElementById('editUserCategory').value = cleanCategory;
             } else {
                 catGroup.style.display = 'none';
             }
             
             // Show modal
             document.getElementById('editUserModal').style.display = 'block';
        }
        
        function closeEditUserModal() {
            document.getElementById('editUserModal').style.display = 'none';
        }
        
        async function submitEditUser() {
            const type = document.getElementById('editUserType').value;
            const originalName = document.getElementById('editUserOriginalName').value;
            const newName = document.getElementById('editUserName').value.trim();
            const newEmail = document.getElementById('editUserEmail').value.trim();
            const admin = document.getElementById('editUserAdmin').value;
            const trader = document.getElementById('editUserTrader').value;
            const category = document.getElementById('editUserCategory').value;
            
            if (!newName) return alert('Name cannot be empty');
            
            const payload = { 
                name: originalName,
                email: newEmail
            };
            
            // Include new_name if changed
            if (newName !== originalName) {
                payload.new_name = newName;
            }
            
            if (type !== 'admin') payload.admin = admin;
            if (type === 'client') {
                payload.trader = trader;
                payload.category = category;
            }
            
            let url = '';
            if (type === 'admin') url = '/api/update_admin';
            else if (type === 'trader') url = '/api/update_trader';
            else if (type === 'client') url = '/api/update_client';
            
            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                
                const contentType = res.headers.get("content-type");
                if (contentType && contentType.indexOf("application/json") !== -1) {
                    const result = await res.json();
                    if (result.status === 'success') {
                        closeEditUserModal();
                        loadData(); 
                    } else {
                        alert('Error: ' + result.message);
                    }
                } else {
                    const text = await res.text();
                    console.error("Non-JSON Response:", text);
                    alert('Server Error: ' + res.status + ' ' + res.statusText);
                }
            } catch (err) {
                console.error(err);
                alert('Network error: ' + err.message);
            }
        }
        
        async function deleteUser(type, name, parent1, parent2) {
            if(event) event.stopPropagation(); // Prevent card click
            const cleanName = name.replace(/\\'/g, "'");
            if (!confirm(`Are you sure you want to delete ${type} "${cleanName}"?\nThis cannot be undone.`)) return;
            // ... (rest of deleteUser)
            
            const payload = {
                type: type,
                name: cleanName,
                admin: (type !== 'admin') ? parent1 : undefined,
                trader: (type === 'client') ? parent2 : undefined
            };

            try {
                const res = await fetch('/api/delete_user', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (result.status === 'success') {
                    loadData();
                    // Reopen modal? No, we are in tree view now. 
                    // Just reload tree.
                } else {
                    alert('Error deleting: ' + result.message);
                }
            } catch (err) {
                console.error(err);
                alert('Network error deleting user');
            }
        }

        async function deleteUser(type, name, parent1, parent2) {
            const cleanName = name.replace(/\\'/g, "'");
            if (!confirm(`Are you sure you want to delete ${type} "${cleanName}"?\nThis cannot be undone.`)) return;
            
            const payload = {
                type: type,
                name: cleanName,
                admin: (type !== 'admin') ? parent1 : undefined,
                trader: (type === 'client') ? parent2 : undefined
            };

            try {
                const res = await fetch('/api/delete_user', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (result.status === 'success') {
                    loadData();
                    // Reopen modal to show updated list
                    setTimeout(() => openUserListModal(type), 500);
                } else {
                    alert('Error deleting: ' + result.message);
                }
            } catch (err) {
                console.error(err);
                alert('Network error deleting user');
            }
        }


        // --- Core Logic ---
        let hierarchyData = {};
        let currentProfile = 'ALL';
        
        // Glue code for new buttons
        function setFilter(profile) {
            changeProfile(profile);
        }

        function formatCurrency(value) {
            const num = parseFloat(value) || 0;
            return '$' + num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
        
        function changeProfile(profile) {
            currentProfile = profile;
            // Update UI
            document.querySelectorAll('.toggle-btn').forEach(btn => btn.classList.remove('active'));
            if(profile === 'ALL') document.getElementById('btn-profile-all').classList.add('active');
            if(profile === 'BEF') document.getElementById('btn-profile-bef').classList.add('active');
            if(profile === 'PRIVATE') document.getElementById('btn-profile-private').classList.add('active');
            
            // Reload Data
            loadData();
        }

        function loadData() {
            // Add loading indicator to stat cards
            debugLog("Loading Data...");
            const p = document.getElementById('grand-total-payouts');
            if(p) p.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            const v = document.getElementById('grand-ev');
            if(v) v.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            
            const totalsUrl = currentProfile === 'ALL' ? '/api/super_admin/totals' : `/api/super_admin/totals?profile=${currentProfile}`;
            
            // 1. Load Hierarchy (Critical for UI)
            fetch('/api/hierarchy')
                .then(r => {
                    if(!r.ok) throw new Error('Failed to load hierarchy');
                    debugLog("Hierarchy Fetch Response OK");
                    return r.json();
                })
                .then(hData => {
                    debugLog(`Hierarchy Loaded: ${Object.keys(hData.admins || {}).length} admins`);
                    hierarchyData = hData;
                    renderTree();
                    updateSelects();
                    updateStats(); // Initial stats based on hierarchy counts
                    debugLog("Hierarchy Render Complete");
                })
                .catch(err => {
                    debugLog("Hierarchy Load Error: " + err.message, 'error');
                    console.error("Hierarchy Load Error:", err);
                    const tree = document.getElementById('hierarchy-tree');
                    if(tree) tree.innerHTML = `<div class="alert alert-danger">Failed to load user hierarchy: ${err.message}</div>`;
                });

            // 2. Load Financial Totals (Independent)
            fetch(totalsUrl)
                .then(r => {
                    if(!r.ok) throw new Error('Failed to load totals');
                    return r.json();
                })
                .then(fData => {
                    if(fData.status === 'success' && fData.totals) {
                        const t = fData.totals;
                        try {
                            document.getElementById('grand-total-payouts').textContent = formatCurrency(t.total_payouts);
                            document.getElementById('grand-total-deposits').textContent = formatCurrency(t.total_deposits);
                            document.getElementById('grand-total-fees').textContent = formatCurrency(t.total_fees);
                            document.getElementById('grand-total-net').textContent = formatCurrency(t.total_net_profit || (t.total_payouts - t.total_deposits));
                            document.getElementById('grand-hedge').textContent = formatCurrency(t.total_hedge);
                            document.getElementById('grand-farming').textContent = formatCurrency(t.total_farming);
                            document.getElementById('grand-ev').textContent = formatCurrency(t.expected_value);
                            document.getElementById('grand-ev-day').textContent = formatCurrency(t.ev_per_day);
                            
                            if (document.getElementById('grand-hwm')) {
                                document.getElementById('grand-hwm').textContent = formatCurrency(t.total_hwm);
                                document.getElementById('grand-lwm').textContent = formatCurrency(t.total_lwm);
                            }
                            
                            document.getElementById('grand-active-accounts').textContent = t.active_accounts;
                            document.getElementById('grand-completed-accounts').textContent = t.completed_accounts;
                            document.getElementById('grand-failed-accounts').textContent = t.failed_accounts;
                            debugLog("Totals Updated");
                        } catch(e) {
                             debugLog("Error updating DOM with totals: " + e.message, 'error');
                        }
                    }
                })
                .catch(err => {
                    debugLog("Totals Load Error: " + err.message, 'error');
                    console.error("Totals Load Error:", err);
                    // Show error state in cards
                    document.getElementById('grand-total-payouts').textContent = 'Error';
                    document.getElementById('grand-ev').textContent = 'Error';
                });
        }


        function updateStats() {
            if(!hierarchyData.admins) return;
            let a=0, t=0, c=0;
            a = Object.keys(hierarchyData.admins).length;
            Object.values(hierarchyData.admins).forEach(adm => {
                const traders = adm.traders || {};
                t += Object.keys(traders).length;
                Object.values(traders).forEach(tr => {
                    let clients = tr.clients || [];
                    if(Array.isArray(tr)) clients = tr; // legacy
                    
                    // Filter stats
                    clients = clients.filter(cl => {
                        if (currentProfile === 'ALL') return true;
                        let cat = 'PRIVATE';
                        if (typeof cl === 'object') {
                            cat = (cl.profile || cl.category || cl.source || 'PRIVATE').toUpperCase();
                        }
                        return cat === currentProfile;
                    });
                    
                    c += clients.length;
                });
            });
            document.getElementById('total-admins').textContent = a;
            document.getElementById('total-traders').textContent = t;
            document.getElementById('total-clients').textContent = c;
        }

        function updateSelects() {
            const selA = document.getElementById('admin-select-trader');
            const selC = document.getElementById('admin-select-client');
            
            // preserve values
            const valA = selA.value;
            const valC = selC.value;
            
            selA.innerHTML = '<option value="">Select Admin...</option>';
            selC.innerHTML = '<option value="">Select Admin...</option>';
            
            if(hierarchyData.admins) {
                Object.keys(hierarchyData.admins).forEach(k => {
                    selA.add(new Option(k, k));
                    selC.add(new Option(k, k));
                });
            }
            if(valA) selA.value = valA;
            if(valC) { selC.value = valC; updateTraderSelect(); }
        }

        function updateTraderSelect() {
            const adminName = document.getElementById('admin-select-client').value;
            const traderSel = document.getElementById('trader-select-client');
            traderSel.innerHTML = '<option value="">Select Trader...</option>';
            
            if(adminName && hierarchyData.admins[adminName] && hierarchyData.admins[adminName].traders) {
                Object.keys(hierarchyData.admins[adminName].traders).forEach(t => {
                    traderSel.add(new Option(t, t));
                });
            }
        }

        // --- Drag and Drop Logic --- (Updated with validation)
        
        function dragStart(ev, type, name, parent1, parent2) {
            ev.stopPropagation(); // Stop event from bubbling up to parents (prevents client drag from triggering trader drag)
            ev.dataTransfer.setData("type", type);
            ev.dataTransfer.setData("name", name);
            ev.dataTransfer.setData("parent1", parent1); // Admin 
            ev.dataTransfer.setData("parent2", parent2); // Trader
            ev.target.classList.add('dragging');
            
            // Store type globally for dragOver check
            window.dragType = type;
        }

        function dragEnd(ev) {
            ev.target.classList.remove('dragging');
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            window.dragType = null;
        }

        function allowDrop(ev, targetType) {
            // Only allow dropping Traders on Admins
            if (window.dragType === 'trader' && targetType !== 'admin') return;
            // Only allow dropping Clients on Traders
            if (window.dragType === 'client' && targetType !== 'trader') return;
            
            ev.preventDefault(); 
            ev.currentTarget.classList.add('drag-over');
        }

        function dragLeave(ev) {
            ev.currentTarget.classList.remove('drag-over');
        }

        async function drop(ev, targetType, targetName, targetAdmin) {
            ev.preventDefault();
            ev.currentTarget.classList.remove('drag-over');
            
            const sourceType = ev.dataTransfer.getData("type");
            const sourceName = ev.dataTransfer.getData("name");
            const oldParent1 = ev.dataTransfer.getData("parent1"); // Admin (source)
            const oldParent2 = ev.dataTransfer.getData("parent2"); // Trader (source)
            
            // 1. Move Trader -> Admin
            if (sourceType === 'trader' && targetType === 'admin') {
                if (oldParent1 === targetName) return; 
                
                // Call API
                const payload = { 
                    type: 'trader', 
                    name: sourceName, 
                    old_admin: oldParent1, 
                    new_admin: targetName 
                };
                
                await performMove(payload);
            }
            // 2. Move Client -> Trader
            else if (sourceType === 'client' && targetType === 'trader') {
                // targetName is the new Trader, targetAdmin is the new Admin
                if (oldParent2 === targetName && oldParent1 === targetAdmin) return;
                
                const payload = {
                    type: 'client',
                    name: sourceName,
                    old_trader: oldParent2,
                    old_admin: oldParent1,
                    new_trader: targetName,
                    new_admin: targetAdmin
                };
                
                await performMove(payload);
            }
        }
        
        async function performMove(payload) {
             if(!confirm(`Confirm move?`)) return;
             try {
                const res = await fetch('/api/move_user', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const result = await res.json();
                if (result.status === 'success') {
                    // alert('Moved successfully');
                    loadData(); 
                } else {
                    alert('Move failed: ' + result.message);
                }
            } catch(e) {
                alert('Network error: ' + e.message);
            }
        }


        function renderTree() {
            const container = document.getElementById('hierarchy-tree');
            container.innerHTML = '';
            
            if (!hierarchyData.admins) return;

            // Robust escaping for HTML attributes: 
            const esc = (s) => (s || '').replace(/[\\']/g, '\\$&').replace(/"/g, '&quot;');

            Object.entries(hierarchyData.admins).forEach(([adminName, adminData]) => {
                const sAdmin = esc(adminName);
                const sAdminEmail = esc(adminData.email);

                // Admin Card
                const card = document.createElement('div');
                card.className = 'admin-card';
                card.style.marginBottom = '12px';
                
                // --- Drop Zone Attributes for Admin (Result: Move Trader here) ---
                card.setAttribute('ondragover', "allowDrop(event, 'admin')");
                card.setAttribute('ondragleave', "dragLeave(event)");
                card.setAttribute('ondrop', `drop(event, 'admin', '${sAdmin}', null)`);
                
                const header = document.createElement('div');
                header.className = 'admin-header';
                // Clickable Header
                header.style.cursor = 'pointer';
                header.onclick = (e) => {
                    if (e.target.closest('button')) return;
                    window.location.href = '/admin/' + encodeURIComponent(adminName);
                };

                // Ultra Compact Layout
                header.style.display = 'flex';
                header.style.justifyContent = 'space-between';
                header.style.alignItems = 'center';
                header.style.padding = '4px 12px';
                header.style.minHeight = '32px';
                
                header.innerHTML = `
                    <div class="admin-title-group" style="display:flex; align-items:center;">
                        <span class="badge badge-admin" style="margin-right:8px; font-size:0.6rem; padding: 1px 5px;">ADMIN</span>
                        <div class="admin-name" style="margin-right:8px; font-size:0.9rem; text-decoration: underline; text-decoration-color: rgba(255,255,255,0.3); text-underline-offset: 2px;">${adminName}</div> 
                        <div class="admin-email" style="font-size:0.75rem; color:rgba(255,255,255,0.9); font-weight:500;">${adminData.email || ''}</div>
                    </div>
                    <div class="action-buttons" style="display:flex; gap:8px; align-items:center;">
                        <a href="/admin/${encodeURIComponent(adminName)}" onclick="event.stopPropagation()" style="color:var(--text-secondary); text-decoration:none;" title="View Dashboard"><i class="fas fa-external-link-alt" style="font-size:0.9rem;"></i></a>
                        <button type="button" onclick="openEditUserModal('admin', '${sAdmin}', '${sAdminEmail}')" style="background:none; border:none; color:var(--text-secondary); cursor:pointer; padding:0 2px;" title="Edit API/Info"><i class="fas fa-edit" style="font-size:0.9rem;"></i></button>
                        <button type="button" onclick="deleteUser('admin', '${sAdmin}')" style="background:none; border:none; color:#ff4d4d; cursor:pointer; padding:0 2px;" title="Delete Admin"><i class="fas fa-trash" style="font-size:0.9rem;"></i></button>
                    </div>
                `;
                card.appendChild(header);
                
                // Trader List
                const tList = document.createElement('div');
                tList.className = 'trader-list';
                tList.style.padding = '8px'; // Reduced padding
                
                const traders = adminData.traders || {};
                Object.entries(traders).forEach(([traderName, traderData]) => {
                    const sTrader = esc(traderName);
                    const sTraderEmail = esc(traderData.email);

                    const tItem = document.createElement('div');
                    tItem.className = 'trader-item';
                    tItem.style.marginBottom = '8px'; // Reduced gap
                    
                    // --- Drag Attributes for Trader (Move this trader) ---
                    tItem.draggable = true;
                    tItem.setAttribute('ondragstart', `dragStart(event, 'trader', '${sTrader}', '${sAdmin}', null)`);
                    tItem.setAttribute('ondragend', `dragEnd(event)`);
                    
                    // --- Drop Zone Attributes for Trader (Result: Move Client here) ---
                    tItem.setAttribute('ondragover', "allowDrop(event, 'trader')");
                    tItem.setAttribute('ondragleave', "dragLeave(event)");
                    tItem.setAttribute('ondrop', `drop(event, 'trader', '${sTrader}', '${sAdmin}')`);

                    
                    // Trader Header - Clickable (Link)
                    const safeTraderLink = '/trader/' + encodeURIComponent(traderName).replace(/'/g, '%27');

                    tItem.innerHTML = `
                        <div class="trader-header" onclick="if(!event.target.closest('button')) window.location.href='${safeTraderLink}'" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center; padding: 4px 8px; min-height: 28px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span class="badge badge-trader" style="font-size:0.6rem; padding: 1px 5px;">TRADER</span>
                                <span class="trader-name" style="font-size:0.85rem; text-decoration: underline; text-decoration-color: rgba(255,255,255,0.3); text-underline-offset: 2px;">${traderName}</span>
                                <span class="trader-email" style="font-size:0.75rem; color:rgba(255,255,255,0.9); font-weight:500;">${traderData.email || ''}</span>
                            </div>
                            <div class="action-buttons" style="display:flex; gap:6px; align-items:center;">
                                <a href="${safeTraderLink}" onclick="event.stopPropagation()" style="color:rgba(255,255,255,0.8); text-decoration:none;" title="View Dashboard"><i class="fas fa-external-link-alt" style="font-size:0.85rem;"></i></a>
                                <button type="button" onclick="openEditUserModal('trader', '${sTrader}', '${sTraderEmail}', '${sAdmin}')" style="background:none; border:none; color:rgba(255,255,255,0.8); cursor:pointer; padding:0 2px;" title="Edit Trader"><i class="fas fa-edit" style="font-size:0.85rem;"></i></button>
                                <button type="button" onclick="deleteUser('trader', '${sTrader}', '${sAdmin}')" style="background:none; border:none; color:#ff4d4d; cursor:pointer; padding:0 2px;" title="Delete Trader"><i class="fas fa-trash" style="font-size:0.85rem;"></i></button>
                            </div>
                        </div>
                    `;
                    
                    // Client Tag List
                    const cList = document.createElement('div');
                    cList.className = 'client-list';
                    cList.style.padding = '10px'; // Reduced padding inside trader box
                    const clients = traderData.clients || [];
                    
                    clients.forEach(c => {
                        // Filter logic
                        if (currentProfile !== 'ALL') {
                            let cat = 'PRIVATE';
                            if (typeof c === 'object') {
                                cat = (c.profile || c.category || c.source || 'PRIVATE').toUpperCase();
                            }
                            if (cat !== currentProfile) return;
                        }

                        const cName = (typeof c === 'object') ? c.name : c;
                        const cEmail = (typeof c === 'object') ? c.email : '';
                        const cCat = (typeof c === 'object') ? (c.category || c.profile || 'Private') : 'Private';
                        
                        const sClient = esc(cName);
                        const sClientEmail = esc(cEmail);
                        const sCat = esc(cCat);
                        
                        const tag = document.createElement('div'); 
                        tag.className = 'client-tag';
                        
                        // --- Drag Attributes for Client ---
                        tag.draggable = true;
                        tag.setAttribute('ondragstart', `dragStart(event, 'client', '${sClient}', '${sAdmin}', '${sTrader}')`);
                        tag.setAttribute('ondragend', `dragEnd(event)`);
                        
                        tag.style.display = 'inline-flex';
                        tag.style.alignItems = 'center';
                        tag.style.gap = '6px';
                        tag.style.padding = '6px 10px'; // Reduced tag size
                        tag.style.fontSize = '0.85rem';
                        
                        tag.innerHTML = `
                            <a href="/dashboard/${cName}" style="color:inherit; text-decoration:none; display:flex; align-items:center;">
                                <i class="fas fa-user-circle" style="margin-right:5px;"></i> ${cName}
                            </a>
                            <div class="mini-actions" style="margin-left:4px; border-left:1px solid rgba(255,255,255,0.2); padding-left:6px; display:flex; gap:4px;">
                                <button type="button" onclick="openEditUserModal('client', '${sClient}', '${sClientEmail}', '${sAdmin}', '${sTrader}', '${sCat}')" style="background:none; border:none; cursor:pointer; font-size:0.75rem; opacity:0.7; color: inherit; padding:0;" title="Edit"><i class="fas fa-pencil-alt"></i></button>
                                <button type="button" onclick="deleteUser('client', '${sClient}', '${sAdmin}', '${sTrader}')" style="background:none; border:none; cursor:pointer; font-size:0.8rem; color:#ff8888; opacity:0.7; padding:0;" title="Delete"><i class="fas fa-times"></i></button>
                            </div>
                        `;
                        
                        cList.appendChild(tag);
                    });
                    
                    tItem.appendChild(cList);
                    tList.appendChild(tItem);
                });
                
                card.appendChild(tList);
                container.appendChild(card);
            });
        }

        // Global Delegation for reliability (Fix for non-clickable cards)
        document.addEventListener('click', function(e) {
            // debugLog(`Click detected on: ${e.target.tagName} - ID: ${e.target.id} - Classes: ${e.target.className}`); // Verbose log

            // Check if clicked element or parent is one of our stat cards
            const card = e.target.closest('.stat-box-modern');
            if (card) {
                debugLog(`Click matched card: ${card.id}`);
                let type = null;
                if (card.id === 'stat-card-admin') type = 'admin';
                else if (card.id === 'stat-card-trader') type = 'trader';
                else if (card.id === 'stat-card-client') type = 'client';

                if (type) {
                     debugLog(`Triggering modal for: ${type}`);
                     e.preventDefault(); 
                     e.stopPropagation();
                     
                     if (window.openUserListModal) {
                        try {
                            window.openUserListModal(type);
                            debugLog(`Modal triggered successfully`);
                        } catch(err) {
                            debugLog(`Modal trigger failed: ${err.message}`, 'error');
                        }
                     } else {
                        debugLog("openUserListModal not defined globally", 'error');
                     }
                }
            }
        }, true); // Capture phase

        // Init
        document.addEventListener('DOMContentLoaded', () => {
             debugLog("DOMContentLoaded - Page Ready");

             // 1. Force Modal to Body Root immediately
             const modal = document.getElementById('userListModal');
             if (modal) {
                 if(modal.parentNode !== document.body) document.body.appendChild(modal);
                 // Reset modal styles just in case
                 modal.style.display = 'none';
                 modal.style.zIndex = '99999';
                 debugLog("Modal moved to body root");
             } else {
                 debugLog("ERROR: userListModal element not found DOM", 'error');
             }

             // 2. Wrap loadData
             try { 
                loadData(); 
                debugLog("Initial data load started");
             } catch(e) { 
                debugLog(`Initial loadData failed: ${e.message}`, 'error');
             }
        });
        
        // Expose to global window
        window.openUserListModal = openUserListModal;
        window.closeUserListModal = closeUserListModal;

        // ── Reset Password ────────────────────────────────────────────────
        async function resetUserPassword(name) {
            if (!confirm(`Reset dashboard login password for "${name}"?\n\nA new random password will be generated.`)) return;
            try {
                const res = await fetch('/api/admin/reset_password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: name})
                });
                const data = await res.json();
                if (data.new_password) {
                    showResetPwModal(name, data.new_password);
                } else {
                    alert('Error: ' + (data.error || 'Failed to reset password'));
                }
            } catch(e) {
                alert('Network error: ' + e.message);
            }
        }

        function showResetPwModal(name, password) {
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:20000;display:flex;align-items:center;justify-content:center;';
            const safeDisplay = password.replace(/</g,'&lt;').replace(/>/g,'&gt;');
            overlay.innerHTML = `
                <div style="background:#1e293b;border:2px solid #60a5fa;border-radius:10px;padding:28px 32px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.6);">
                    <h3 style="color:#f8fafc;margin:0 0 8px;">&#128273; Password Reset</h3>
                    <p style="color:#94a3b8;margin:0 0 16px;font-size:0.9rem;"><strong style="color:#f1f5f9;">${name}</strong>'s new login password:</p>
                    <div style="display:flex;align-items:center;gap:8px;background:#0f172a;border:1px solid #334155;border-radius:6px;padding:12px 16px;">
                        <code id="superAdminResetPw" style="flex:1;color:#fbbf24;font-size:1.15rem;letter-spacing:0.08em;word-break:break-all;">${safeDisplay}</code>
                        <button id="superAdminCopyPwBtn" onclick="(function(btn){navigator.clipboard&&navigator.clipboard.writeText('${password.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}').then(()=>{btn.textContent='✓';setTimeout(()=>btn.textContent='📋',1500)}).catch(()=>{})})(this)" style="flex-shrink:0;background:none;border:none;cursor:pointer;color:#60a5fa;font-size:1.3rem;" title="Copy to clipboard">📋</button>
                    </div>
                    <p style="color:#ef4444;font-size:0.78rem;margin:12px 0 0;">⚠ Copy this now — it will not be shown again.</p>
                    <div style="text-align:right;margin-top:22px;">
                        <button onclick="this.closest('div[style*=position]').remove()" style="padding:9px 22px;background:#475569;color:white;border:none;border-radius:5px;cursor:pointer;font-weight:bold;">Close</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);
            overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
        }
    