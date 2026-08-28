import os
import sys
import uvicorn
import logging
import csv
import io
from fastapi import Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from google.adk.cli.fast_api import get_fast_api_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration_readiness_checker")

# Locate the directory containing the 'agents' folder
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(AGENT_DIR)

# Import shared helpers from local test runner
from test_locally import run_agent_locally, map_source_engine, map_target_engine, map_provider

# Create the base FastAPI app from ADK
app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=False,
    allow_origins=["*"]
)

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Database Migration Readiness Dashboard</title>
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- FontAwesome Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Marked.js for Markdown parsing -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        .gcp-blue { color: #1a73e8; }
        .gcp-bg-blue { background-color: #1a73e8; }
        .gcp-bg-blue:hover { background-color: #1557b0; }
        /* Style generated markdown tables */
        .markdown-body table {
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }
        .markdown-body th, .markdown-body td {
            border: 1px solid #e2e8f0;
            padding: 0.75rem;
            text-align: left;
        }
        .markdown-body th {
            background-color: #f8fafc;
            font-weight: 600;
        }
        .markdown-body pre {
            background-color: #0f172a;
            color: #f8fafc;
            padding: 1rem;
            border-radius: 0.375rem;
            overflow-x: auto;
            margin: 1rem 0;
            font-family: monospace;
        }
        .markdown-body code {
            font-family: monospace;
            background-color: #f1f5f9;
            padding: 0.125rem 0.25rem;
            border-radius: 0.25rem;
            color: #0f172a;
        }
        .markdown-body pre code {
            background-color: transparent;
            padding: 0;
            color: inherit;
        }
        .markdown-body h1 { font-size: 1.875rem; font-weight: 700; margin-top: 1.5rem; margin-bottom: 1rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }
        .markdown-body h2 { font-size: 1.5rem; font-weight: 600; margin-top: 1.5rem; margin-bottom: 0.75rem; }
        .markdown-body h3 { font-size: 1.25rem; font-weight: 600; margin-top: 1.25rem; margin-bottom: 0.5rem; }
        .markdown-body p { margin-bottom: 1rem; line-height: 1.625; }
        .markdown-body ul, .markdown-body ol { margin-left: 1.5rem; margin-bottom: 1rem; list-style-type: decimal; }
        .markdown-body blockquote {
            border-left: 4px solid #1a73e8;
            padding-left: 1rem;
            margin: 1rem 0;
            color: #475569;
            font-style: italic;
        }
    </style>
</head>
<body class="bg-gray-50 text-gray-800 font-sans min-h-screen flex flex-col">

    <!-- Top Header -->
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm">
        <div class="flex items-center space-x-3">
            <div class="gcp-bg-blue p-2 rounded-lg text-white">
                <i class="fa-solid fa-database text-xl"></i>
            </div>
            <div>
                <h1 class="text-xl font-bold tracking-tight">Database Migration Readiness Checker</h1>
                <p class="text-xs text-gray-500">Autonomous diagnostic agent & playbook generator</p>
            </div>
        </div>
        <div class="flex items-center space-x-4">
            <span class="text-sm bg-blue-50 text-blue-700 px-3 py-1 rounded-full font-medium border border-blue-100">
                <i class="fa-solid fa-robot mr-1.5"></i> Google DeepMind ADK
            </span>
        </div>
    </header>

    <!-- Main Container -->
    <div class="flex-grow flex flex-col lg:flex-row">
        
        <!-- Left Side: Controls -->
        <aside class="w-full lg:w-1/3 bg-white border-r border-gray-200 p-6 flex flex-col space-y-6">
            
            <!-- Navigation Tabs -->
            <div class="flex border-b border-gray-200">
                <button id="tab-run-btn" class="flex-1 pb-3 text-sm font-semibold border-b-2 border-blue-600 text-blue-600 focus:outline-none" onclick="switchTab('run')">
                    <i class="fa-solid fa-play mr-2"></i>Generate / Run
                </button>
                <button id="tab-eval-btn" class="flex-1 pb-3 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 focus:outline-none" onclick="switchTab('eval')">
                    <i class="fa-solid fa-clipboard-check mr-2"></i>Evaluate CSV
                </button>
            </div>

            <!-- Tab 1 Form: Run / Generate -->
            <form id="readiness-form" class="space-y-4" onsubmit="handleFormSubmit(event)">
                
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Execution Mode</label>
                    <select id="execution_mode" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500" onchange="toggleModeFields()">
                        <option value="Generate Playbook Only">Generate Playbook Only (Static)</option>
                        <option value="Run Automated Diagnostics">Run Automated Diagnostics (Live Queries)</option>
                    </select>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Source Engine</label>
                        <select id="source_engine" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="MySQL">MySQL</option>
                            <option value="PostgreSQL">PostgreSQL</option>
                            <option value="SQL Server">SQL Server</option>
                            <option value="Oracle">Oracle</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Target Engine</label>
                        <select id="target_engine" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="Cloud SQL for MySQL">Cloud SQL for MySQL</option>
                            <option value="Cloud SQL for PostgreSQL">Cloud SQL for PostgreSQL</option>
                            <option value="Cloud SQL for SQL Server">Cloud SQL for SQL Server</option>
                            <option value="AlloyDB">AlloyDB</option>
                        </select>
                    </div>
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Source Provider</label>
                    <select id="source_provider" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                        <option value="On-premise/Self-hosted">On-premise/Self-hosted</option>
                        <option value="AWS RDS/Aurora">AWS RDS/Aurora</option>
                        <option value="Azure Database">Azure Database</option>
                    </select>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Database Name</label>
                        <input type="text" id="database_name" value="my_db" required class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Migration User</label>
                        <input type="text" id="migration_user" value="migration_user" required class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                    </div>
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Migration Strategy</label>
                    <select id="migration_type" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                        <option value="Online CDC">Online CDC (Continuous Replication)</option>
                        <option value="Offline/One-time Dump">Offline/One-time Dump</option>
                    </select>
                </div>

                <!-- Section: Live Connection Fields (Hidden by default) -->
                <div id="live-connection-fields" class="hidden border-t border-gray-200 pt-4 space-y-4">
                    <h3 class="text-sm font-semibold text-gray-900"><i class="fa-solid fa-link mr-1.5 text-blue-600"></i>Source Database Connection</h3>
                    <div class="grid grid-cols-3 gap-2">
                        <div class="col-span-2">
                            <label class="block text-xs font-medium text-gray-500 mb-1">Host/IP</label>
                            <input type="text" id="source_host" placeholder="10.0.0.4" class="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-gray-500 mb-1">Port</label>
                            <input type="number" id="source_port" placeholder="3306" class="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="block text-xs font-medium text-gray-500 mb-1">Username</label>
                            <input type="text" id="source_user" placeholder="root" class="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-gray-500 mb-1">Password</label>
                            <input type="password" id="source_password" placeholder="••••••••" class="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
                        </div>
                    </div>

                    <h3 class="text-sm font-semibold text-gray-900"><i class="fa-solid fa-cloud mr-1.5 text-blue-600"></i>GCP Target Environment</h3>
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="block text-xs font-medium text-gray-500 mb-1">GCP Project ID</label>
                            <input type="text" id="target_gcp_project" placeholder="my-gcp-project" class="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-gray-500 mb-1">Target Instance ID</label>
                            <input type="text" id="target_gcp_instance" placeholder="my-instance" class="w-full border border-gray-300 rounded-md px-2 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
                        </div>
                    </div>
                </div>

                <button type="submit" class="w-full gcp-bg-blue text-white rounded-md py-2.5 font-semibold text-sm shadow hover:bg-blue-700 transition flex items-center justify-center space-x-2">
                    <i class="fa-solid fa-gears"></i>
                    <span>Execute Readiness Checks</span>
                </button>
            </form>

            <!-- Tab 2 Form: Evaluate Playbook -->
            <form id="evaluation-form" class="hidden space-y-4" onsubmit="handleEvaluationSubmit(event)">
                
                <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-800 space-y-2">
                    <p class="font-semibold"><i class="fa-solid fa-circle-info mr-1"></i>How to evaluate completed playbooks:</p>
                    <ol class="list-decimal list-inside space-y-1 text-xs">
                        <li>Generate a playbook first (Tab 1).</li>
                        <li>Download the CSV checklist and open it in Excel/Sheets.</li>
                        <li>Run the queries manually, write results in the <b>Actual Output</b> column, and select <b>PASS/FAIL</b>.</li>
                        <li>Upload your completed CSV below to verify readiness.</li>
                    </ol>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Source Engine</label>
                        <select id="eval_source_engine" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="MySQL">MySQL</option>
                            <option value="PostgreSQL">PostgreSQL</option>
                            <option value="SQL Server">SQL Server</option>
                            <option value="Oracle">Oracle</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Target Engine</label>
                        <select id="eval_target_engine" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="Cloud SQL for MySQL">Cloud SQL for MySQL</option>
                            <option value="Cloud SQL for PostgreSQL">Cloud SQL for PostgreSQL</option>
                            <option value="Cloud SQL for SQL Server">Cloud SQL for SQL Server</option>
                            <option value="AlloyDB">AlloyDB</option>
                        </select>
                    </div>
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Source Provider</label>
                    <select id="eval_provider" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                        <option value="On-premise/Self-hosted">On-premise/Self-hosted</option>
                        <option value="AWS RDS/Aurora">AWS RDS/Aurora</option>
                        <option value="Azure Database">Azure Database</option>
                    </select>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Database Name</label>
                        <input type="text" id="eval_database" value="my_db" required class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Migration User</label>
                        <input type="text" id="eval_migration_user" value="migration_user" required class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                    </div>
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Migration Strategy</label>
                    <select id="eval_migration_type" class="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                        <option value="Online CDC">Online CDC (Continuous Replication)</option>
                        <option value="Offline/One-time Dump">Offline/One-time Dump</option>
                    </select>
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-1">Upload Completed CSV Checklist</label>
                    <div class="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-md hover:border-blue-400 transition cursor-pointer relative">
                        <div class="space-y-1 text-center">
                            <i class="fa-solid fa-file-csv text-4xl text-gray-400 mb-2"></i>
                            <div class="flex text-sm text-gray-600">
                                <span class="relative font-medium text-blue-600 hover:text-blue-500">Upload a file</span>
                                <p class="pl-1">or drag and drop</p>
                            </div>
                            <p class="text-xs text-gray-500">completed_playbook.csv</p>
                        </div>
                        <input id="csv_file" type="file" accept=".csv" required class="absolute inset-0 opacity-0 cursor-pointer" onchange="updateFileName(this)">
                    </div>
                    <p id="file-name-text" class="text-xs text-green-600 font-medium mt-1"></p>
                </div>

                <button type="submit" class="w-full bg-green-600 text-white rounded-md py-2.5 font-semibold text-sm shadow hover:bg-green-700 transition flex items-center justify-center space-x-2">
                    <i class="fa-solid fa-clipboard-check"></i>
                    <span>Verify Readiness Assessment</span>
                </button>
            </form>
        </aside>

        <!-- Right Side: Outputs -->
        <main class="flex-grow p-6 flex flex-col space-y-6">
            
            <!-- Default Welcome Display -->
            <div id="welcome-pane" class="flex-grow flex flex-col items-center justify-center text-center p-8 bg-white border border-gray-200 rounded-xl shadow-sm space-y-4">
                <div class="bg-blue-100 p-6 rounded-full text-blue-600 animate-bounce">
                    <i class="fa-solid fa-robot text-5xl"></i>
                </div>
                <div class="max-w-lg space-y-4">
                    <h2 class="text-2xl font-bold text-gray-900">Hello! I'm your Migration Readiness Agent.</h2>
                    <p class="text-sm text-gray-600 leading-relaxed">
                        I am here to guide you through auditing, sizing, and preparing your databases for cloud migration. I can dynamically analyze configurations, warn you of active lock risks, and perform auto-remediations!
                    </p>
                    
                    <div class="border-t border-gray-100 my-4 pt-4 text-left">
                        <h4 class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">What I can do for you:</h4>
                        <ul class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-gray-600">
                            <li class="flex items-start">
                                <i class="fa-solid fa-circle-check text-green-500 mr-2 mt-0.5"></i>
                                <span><strong>Pre-Migration Audits</strong>: Inspect configurations, users, permissions, versions, and MyISAM tables.</span>
                            </li>
                            <li class="flex items-start">
                                <i class="fa-solid fa-circle-check text-green-500 mr-2 mt-0.5"></i>
                                <span><strong>Target Sizing Advice</strong>: Recommend instance sizes (vCPUs/Memory/Storage) based on database size & load.</span>
                            </li>
                            <li class="flex items-start">
                                <i class="fa-solid fa-circle-check text-green-500 mr-2 mt-0.5"></i>
                                <span><strong>Firewall Constructor</strong>: Detect port blocks and output target <code>gcloud</code> firewall rules.</span>
                            </li>
                            <li class="flex items-start">
                                <i class="fa-solid fa-circle-check text-green-500 mr-2 mt-0.5"></i>
                                <span><strong>Active Load Checks</strong>: Audit current active connections and InnoDB lock waits to prevent crashes.</span>
                            </li>
                        </ul>
                    </div>
                    
                    <p class="text-xs text-blue-600 font-semibold bg-blue-50 py-2 px-4 rounded-lg inline-block">
                        👈 Configure your settings in the sidebar to get started!
                    </p>
                </div>
            </div>

            <!-- Loading Spinner -->
            <div id="loading-pane" class="hidden flex-grow flex-col items-center justify-center text-center p-8 bg-white border border-gray-200 rounded-xl shadow-sm space-y-4">
                <svg class="animate-spin h-10 w-10 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <div>
                    <h3 class="text-lg font-semibold text-gray-900">Agent is Analyzing Environments</h3>
                    <p class="text-xs text-gray-500 mt-1">This can take up to 30-45 seconds to generate plan details...</p>
                </div>
            </div>

            <!-- Results Output -->
            <div id="results-pane" class="hidden flex-grow flex flex-col bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden min-h-[500px]">
                
                <!-- Agent Guide Banner -->
                <div id="agent-guide-banner" class="bg-blue-50 border-b border-blue-100 px-6 py-3 flex items-start space-x-3 text-sm text-blue-800">
                    <i class="fa-solid fa-comment-dots text-lg text-blue-500 mt-0.5"></i>
                    <div>
                        <p class="font-semibold">Agent Advice & Next Steps:</p>
                        <p id="agent-advice-text" class="text-xs text-blue-700 mt-0.5">I have analyzed your environment. Download the checklist, execute outstanding manual fixes, or configure replication settings on the target.</p>
                    </div>
                </div>

                <!-- Action Buttons & Header -->
                <div class="bg-gray-50 border-b border-gray-200 px-6 py-4 flex flex-col sm:flex-row items-start sm:items-center justify-between space-y-2 sm:space-y-0">
                    <h2 class="font-bold text-gray-900"><i class="fa-solid fa-file-lines mr-1.5 text-blue-600"></i>Generated Assessment Output</h2>
                    <div class="flex items-center space-x-2">
                        <button onclick="downloadMarkdown()" class="bg-white border border-gray-300 text-gray-700 rounded-md px-3 py-1.5 text-xs font-semibold shadow-sm hover:bg-gray-50 transition flex items-center">
                            <i class="fa-solid fa-file-arrow-down mr-1.5 text-blue-600"></i>Download Playbook (.md)
                        </button>
                        <button onclick="downloadCSV()" class="bg-white border border-gray-300 text-gray-700 rounded-md px-3 py-1.5 text-xs font-semibold shadow-sm hover:bg-gray-50 transition flex items-center">
                            <i class="fa-solid fa-table mr-1.5 text-green-600"></i>Download Checklist (.csv)
                        </button>
                    </div>
                </div>

                <!-- Markdown Content Render -->
                <div class="p-6 overflow-y-auto flex-grow max-h-[70vh]">
                    <div id="markdown-container" class="markdown-body"></div>
                </div>
            </div>

        </main>
    </div>

    <!-- Interactive Decision Modal -->
    <div id="decision-modal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full flex items-center justify-center z-50">
        <div class="relative p-6 border w-[480px] max-w-lg shadow-lg rounded-md bg-white space-y-4">
            <div class="text-center">
                <div class="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-yellow-100 text-yellow-600 mb-2">
                    <i class="fa-solid fa-triangle-exclamation text-2xl"></i>
                </div>
                <h3 class="text-lg leading-6 font-medium text-gray-900">Issues Detected</h3>
                <div class="mt-2 px-7 py-3">
                    <p class="text-sm text-gray-500 mb-3">
                        The diagnostics check failed on some source database configurations. Would you like the agent to fix these issues automatically, or just generate the manual runbook?
                    </p>
                    <!-- Dynamic issues list -->
                    <div class="text-left bg-gray-50 rounded-lg p-3 border border-gray-200 max-h-48 overflow-y-auto">
                        <p class="text-xs font-bold text-gray-600 mb-2 uppercase tracking-wide"><i class="fa-solid fa-screwdriver-wrench mr-1"></i>Found gaps I can fix:</p>
                        <ul id="modal-issues-list" class="list-disc list-inside text-xs text-gray-500 space-y-1.5 leading-normal"></ul>
                    </div>
                </div>
            </div>
            <div class="flex flex-col space-y-2">
                <button onclick="acceptAutoFix()" class="w-full bg-blue-600 text-white rounded-md py-2 text-sm font-semibold hover:bg-blue-700 transition flex items-center justify-center space-x-1.5">
                    <i class="fa-solid fa-wand-magic-sparkles"></i>
                    <span>Yes, Let Agent Fix Issues</span>
                </button>
                <button onclick="declineAutoFix()" class="w-full bg-gray-100 text-gray-700 rounded-md py-2 text-sm font-semibold hover:bg-gray-200 transition flex items-center justify-center space-x-1.5">
                    <i class="fa-solid fa-file-invoice"></i>
                    <span>No, Just Show Runbook</span>
                </button>
            </div>
        </div>
    </div>

    <!-- Page Footer -->
    <footer class="bg-white border-t border-gray-200 py-4 px-6 text-center text-xs text-gray-500">
        Database Migration Readiness Checker Tool © 2026. Made with Google DeepMind ADK library.
    </footer>

    <!-- JavaScript logic -->
    <script>
        let currentTab = 'run';
        let generatedPlaybookMarkdown = "";
        let generatedPlaybookCSV = "";
        let lastDatabaseName = "my_db";

        function switchTab(tab) {
            currentTab = tab;
            document.getElementById('tab-run-btn').className = tab === 'run' 
                ? "flex-1 pb-3 text-sm font-semibold border-b-2 border-blue-600 text-blue-600 focus:outline-none"
                : "flex-1 pb-3 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 focus:outline-none";
            document.getElementById('tab-eval-btn').className = tab === 'eval'
                ? "flex-1 pb-3 text-sm font-semibold border-b-2 border-blue-600 text-blue-600 focus:outline-none"
                : "flex-1 pb-3 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 focus:outline-none";

            if (tab === 'run') {
                document.getElementById('readiness-form').classList.remove('hidden');
                document.getElementById('evaluation-form').classList.add('hidden');
            } else {
                document.getElementById('readiness-form').classList.add('hidden');
                document.getElementById('evaluation-form').classList.remove('hidden');
            }
        }

        function toggleModeFields() {
            const mode = document.getElementById('execution_mode').value;
            const liveFields = document.getElementById('live-connection-fields');
            if (mode === 'Run Automated Diagnostics') {
                liveFields.classList.remove('hidden');
            } else {
                liveFields.classList.add('hidden');
            }
        }

        function updateFileName(input) {
            const file = input.files[0];
            const text = document.getElementById('file-name-text');
            if (file) {
                text.innerText = `Selected file: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            } else {
                text.innerText = "";
            }
        }

        function showLoading(show) {
            if (show) {
                document.getElementById('welcome-pane').classList.add('hidden');
                document.getElementById('results-pane').classList.add('hidden');
                document.getElementById('loading-pane').classList.remove('hidden');
            } else {
                document.getElementById('loading-pane').classList.add('hidden');
            }
        }

        function renderResults(data, dbName, mode) {
            const md = data.markdown_playbook || data.playbook_markdown || "";
            const csv = data.csv_playbook || data.playbook_csv || "";
            generatedPlaybookMarkdown = md;
            generatedPlaybookCSV = csv;
            lastDatabaseName = dbName;

            document.getElementById('markdown-container').innerHTML = marked.parse(md);
            
            // Dynamic Agent Advice Logic
            const adviceText = document.getElementById('agent-advice-text');
            if (mode === 'Evaluate CSV') {
                const hasFailures = md.includes('🔴 FAIL') || md.includes('🟡 WARNING');
                if (hasFailures) {
                    adviceText.innerText = "I have evaluated your manual spreadsheet checklist. Some checks still require attention (marked in RED/YELLOW). Execute the fixes and re-verify when ready.";
                } else {
                    adviceText.innerText = "Excellent news! I have validated your manual checklist. All requirements are satisfied. You are ready to start the migration!";
                }
            } else if (mode === 'Run Automated Diagnostics') {
                const hasFailures = md.includes('🔴 FAIL') || md.includes('🟡 WARNING');
                if (hasFailures) {
                    adviceText.innerText = "I detected configuration gaps during live analysis. Select 'Yes, Let Agent Fix' to let me attempt auto-remediation, or manually execute the checklist steps.";
                } else {
                    adviceText.innerText = "Perfect! I ran live audits on your source and target and verified everything is fully ready. You can safely schedule replication!";
                }
            } else {
                adviceText.innerText = "I have compiled a custom static migration checklist. Next steps: Run these queries manually on your source DB, write findings in the CSV, and upload it in 'Evaluate CSV' tab.";
            }

            document.getElementById('welcome-pane').classList.add('hidden');
            document.getElementById('results-pane').classList.remove('hidden');
        }

        let lastPayload = null;
        let lastData = null;

        async function handleFormSubmit(e) {
            e.preventDefault();
            showLoading(true);

            const mode = document.getElementById('execution_mode').value;
            const sourceEngine = document.getElementById('source_engine').value;
            const targetEngine = document.getElementById('target_engine').value;
            const sourceProvider = document.getElementById('source_provider').value;
            const databaseName = document.getElementById('database_name').value;
            const migrationUser = document.getElementById('migration_user').value;
            const migrationType = document.getElementById('migration_type').value;

            // Step 1: Detect failures first (auto_remediate is false initially)
            const payload = {
                execution_mode: mode,
                auto_remediate: false,
                source_engine: sourceEngine,
                target_engine: targetEngine,
                source_provider: sourceProvider,
                database_name: databaseName,
                migration_user: migrationUser,
                migration_type: migrationType
            };

            if (mode === 'Run Automated Diagnostics') {
                payload.source_host = document.getElementById('source_host').value;
                payload.source_port = document.getElementById('source_port').value ? parseInt(document.getElementById('source_port').value) : null;
                payload.source_user = document.getElementById('source_user').value;
                payload.source_password = document.getElementById('source_password').value;
                payload.target_gcp_project = document.getElementById('target_gcp_project').value;
                payload.target_gcp_instance = document.getElementById('target_gcp_instance').value;
            }

            try {
                const response = await fetch('/api/run-readiness', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                showLoading(false);

                if (data.error) {
                    alert(`Error running checks: ${data.error}`);
                    return;
                }

                // If failures are found in Automated Diagnostics Mode, ask the user what to do next
                const hasFailures = mode === 'Run Automated Diagnostics' && (
                    (data.source_steps && data.source_steps.some(step => step.status === 'FAIL')) ||
                    (data.target_steps && data.target_steps.some(step => step.status === 'FAIL'))
                );

                if (hasFailures) {
                    lastPayload = payload;
                    lastData = data;
                    
                    // Populate issues list in the modal dynamically
                    const listElement = document.getElementById('modal-issues-list');
                    listElement.innerHTML = "";
                    
                    const failedSteps = [];
                    if (data.source_steps) {
                        data.source_steps.forEach(step => {
                            if (step.status === 'FAIL' || step.status === 'WARNING') {
                                failedSteps.push(step);
                            }
                        });
                    }
                    if (data.target_steps) {
                        data.target_steps.forEach(step => {
                            if (step.status === 'FAIL' || step.status === 'WARNING') {
                                failedSteps.push(step);
                            }
                        });
                    }
                    
                    failedSteps.forEach(step => {
                        const li = document.createElement('li');
                        li.className = "pl-1";
                        li.innerHTML = `<span class="font-bold text-gray-700">${step.title}</span>: ${step.description}`;
                        listElement.appendChild(li);
                    });

                    document.getElementById('decision-modal').classList.remove('hidden');
                } else {
                    renderResults(data, databaseName, mode);
                }
            } catch (err) {
                showLoading(false);
                alert(`Request failed: ${err.message}`);
            }
        }

        async function acceptAutoFix() {
            document.getElementById('decision-modal').classList.add('hidden');
            showLoading(true);

            // Step 2: User requested Auto-Fix
            lastPayload.auto_remediate = true;

            try {
                const response = await fetch('/api/run-readiness', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(lastPayload)
                });
                const data = await response.json();
                showLoading(false);

                if (data.error) {
                    alert(`Error executing remediation: ${data.error}`);
                    return;
                }

                renderResults(data, lastPayload.database_name, lastPayload.execution_mode);
            } catch (err) {
                showLoading(false);
                alert(`Remediation failed: ${err.message}`);
            }
        }

        function declineAutoFix() {
            document.getElementById('decision-modal').classList.add('hidden');
            // Just display the failed report/playbook
            renderResults(lastData, lastPayload.database_name, lastPayload.execution_mode);
        }

        async function handleEvaluationSubmit(e) {
            e.preventDefault();
            showLoading(true);

            const sourceEngine = document.getElementById('eval_source_engine').value;
            const targetEngine = document.getElementById('eval_target_engine').value;
            const provider = document.getElementById('eval_provider').value;
            const database = document.getElementById('eval_database').value;
            const migrationUser = document.getElementById('eval_migration_user').value;
            const migrationType = document.getElementById('eval_migration_type').value;
            const csvFileInput = document.getElementById('csv_file');

            const formData = new FormData();
            formData.append('source_engine', sourceEngine);
            formData.append('target_engine', targetEngine);
            formData.append('provider', provider);
            formData.append('database', database);
            formData.append('migration_user', migrationUser);
            formData.append('migration_type', migrationType);
            formData.append('csv_file', csvFileInput.files[0]);

            try {
                const response = await fetch('/api/evaluate-playbook', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                showLoading(false);

                if (data.error) {
                    alert(`Error evaluating playbook: ${data.error}`);
                    return;
                }

                renderResults(data, database, 'Evaluate CSV');
            } catch (err) {
                showLoading(false);
                alert(`Request failed: ${err.message}`);
            }
        }

        function downloadMarkdown() {
            if (!generatedPlaybookMarkdown) return;
            const blob = new Blob([generatedPlaybookMarkdown], { type: 'text/markdown;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `migration_playbook_${lastDatabaseName}.md`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        function downloadCSV() {
            if (!generatedPlaybookCSV) return;
            const blob = new Blob([generatedPlaybookCSV], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `playbook_checklist_${lastDatabaseName}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=RedirectResponse)
async def root_redirect():
    return RedirectResponse(url="/dashboard")

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return HTMLResponse(content=HTML_CONTENT)

@app.post("/api/run-readiness")
async def api_run_readiness(request: Request):
    try:
        input_data = await request.json()
        
        # Parse inputs
        input_data["source_engine"] = map_source_engine(input_data.get("source_engine", "MySQL"))
        input_data["target_engine"] = map_target_engine(input_data.get("target_engine", "Cloud SQL for MySQL"))
        input_data["source_provider"] = map_provider(input_data.get("source_provider", "onprem"))
        
        playbook = await run_agent_locally(input_data)
        
        if not playbook:
            return JSONResponse(content={"error": "Agent failed to generate response"}, status_code=500)
            
        return JSONResponse(content=playbook)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/api/evaluate-playbook")
async def api_evaluate_playbook(
    source_engine: str = Form("MySQL"),
    target_engine: str = Form("Cloud SQL for MySQL"),
    provider: str = Form("onprem"),
    database: str = Form(...),
    migration_user: str = Form("migration_user"),
    migration_type: str = Form("Online CDC"),
    csv_file: UploadFile = File(...)
):
    try:
        # Read and parse CSV file
        csv_bytes = await csv_file.read()
        csv_text = csv_bytes.decode("utf-8")
        
        # Parse CSV text using Python csv module
        completed_steps = []
        reader = csv.DictReader(io.StringIO(csv_text))
        for idx, row in enumerate(reader):
            # Strip whitespace from keys and values
            row = {k.strip(): v.strip() if v else "" for k, v in row.items()}
            required_keys = ["Step Number", "Category", "Title", "Command to Run", "Expected Output", "Remediation"]
            missing_keys = [k for k in required_keys if k not in row]
            if missing_keys:
                return JSONResponse(content={"error": f"CSV missing columns: {missing_keys} at row {idx+1}"}, status_code=400)
                
            completed_steps.append({
                "step_number": int(row["Step Number"]),
                "category": row["Category"],
                "title": row["Title"],
                "description": row.get("Description", ""),
                "command_to_run": row["Command to Run"],
                "expected_output": row["Expected Output"],
                "actual_output": row.get("Actual Output") if row.get("Actual Output") else None,
                "status": row.get("Status", "NOT_RUN") if row.get("Status") else "NOT_RUN",
                "remediation": row["Remediation"]
            })
            
        input_data = {
            "execution_mode": "Evaluate Playbook",
            "source_engine": map_source_engine(source_engine),
            "target_engine": map_target_engine(target_engine),
            "source_provider": map_provider(provider),
            "database_name": database,
            "migration_user": migration_user,
            "migration_type": migration_type,
            "completed_steps": completed_steps
        }
        
        playbook = await run_agent_locally(input_data)
        
        if not playbook:
            return JSONResponse(content={"error": "Agent failed to evaluate playbook"}, status_code=500)
            
        return JSONResponse(content=playbook)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

if __name__ == "__main__":
    # Use PORT env variable if running in Cloud Run, or default to 8080
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Running FastAPI server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
