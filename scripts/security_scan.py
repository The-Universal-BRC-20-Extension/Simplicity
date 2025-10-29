#!/usr/bin/env python3
"""
Security Scanning Script for Universal BRC-20 Indexer

This script provides comprehensive security scanning using Bandit and generates
detailed reports for both development and CI environments.
"""

import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path


def run_bandit_scan(output_format="txt", output_file=None):
    """Run bandit security scan with specified output format."""
    cmd = ["pipenv", "run", "bandit", "-r", "src", "-f", output_format]
    
    if output_file:
        cmd.extend(["-o", output_file])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout, result.stderr, 0
    except subprocess.CalledProcessError as e:
        return e.stdout, e.stderr, e.returncode


def analyze_bandit_report(report_file):
    """Analyze bandit JSON report and provide summary."""
    if not os.path.exists(report_file):
        print(f"Report file {report_file} not found.")
        return
    
    with open(report_file, 'r') as f:
        data = json.load(f)
    
    print("\n" + "="*60)
    print("BANDIT SECURITY SCAN REPORT")
    print("="*60)
    
    # Summary metrics
    metrics = data.get('metrics', {}).get('_totals', {})
    print(f"\n📊 SCAN SUMMARY:")
    print(f"   Total lines of code: {metrics.get('loc', 0):,}")
    print(f"   Issues found: {len(data.get('results', []))}")
    print(f"   Files scanned: {len(data.get('metrics', {})) - 1}")  # Exclude _totals
    
    # Severity breakdown
    severity_counts = {
        'HIGH': metrics.get('SEVERITY.HIGH', 0),
        'MEDIUM': metrics.get('SEVERITY.MEDIUM', 0),
        'LOW': metrics.get('SEVERITY.LOW', 0),
    }
    
    print(f"\n🚨 SEVERITY BREAKDOWN:")
    for severity, count in severity_counts.items():
        icon = "🔴" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
        print(f"   {icon} {severity}: {count}")
    
    # Confidence breakdown
    confidence_counts = {
        'HIGH': metrics.get('CONFIDENCE.HIGH', 0),
        'MEDIUM': metrics.get('CONFIDENCE.MEDIUM', 0),
        'LOW': metrics.get('CONFIDENCE.LOW', 0),
    }
    
    print(f"\n🎯 CONFIDENCE BREAKDOWN:")
    for confidence, count in confidence_counts.items():
        icon = "🔴" if confidence == "HIGH" else "🟡" if confidence == "MEDIUM" else "🟢"
        print(f"   {icon} {confidence}: {count}")
    
    # Detailed issues
    results = data.get('results', [])
    if results:
        print(f"\n📋 DETAILED ISSUES:")
        for i, issue in enumerate(results, 1):
            severity = issue.get('issue_severity', 'UNKNOWN')
            confidence = issue.get('issue_confidence', 'UNKNOWN')
            test_name = issue.get('test_name', 'UNKNOWN')
            filename = issue.get('filename', 'UNKNOWN')
            line = issue.get('line_number', 'UNKNOWN')
            text = issue.get('issue_text', 'No description')
            
            severity_icon = "🔴" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
            confidence_icon = "🔴" if confidence == "HIGH" else "🟡" if confidence == "MEDIUM" else "🟢"
            
            print(f"\n   {i}. {severity_icon} {severity} | {confidence_icon} {confidence}")
            print(f"      Test: {test_name}")
            print(f"      File: {filename}:{line}")
            print(f"      Issue: {text}")
    else:
        print(f"\n✅ No security issues found!")
    
    print("\n" + "="*60)


def generate_html_report(json_report_file, html_output_file):
    """Generate HTML report from JSON bandit report."""
    if not os.path.exists(json_report_file):
        print(f"JSON report file {json_report_file} not found.")
        return
    
    with open(json_report_file, 'r') as f:
        data = json.load(f)
    
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bandit Security Report - Universal BRC-20 Indexer</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f5f5f5; padding: 20px; border-radius: 5px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .metric {{ background: white; padding: 15px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .high {{ border-left: 4px solid #dc3545; }}
        .medium {{ border-left: 4px solid #ffc107; }}
        .low {{ border-left: 4px solid #28a745; }}
        .issue {{ background: white; margin: 10px 0; padding: 15px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .severity-high {{ border-left: 4px solid #dc3545; }}
        .severity-medium {{ border-left: 4px solid #ffc107; }}
        .severity-low {{ border-left: 4px solid #28a745; }}
        .code {{ background: #f8f9fa; padding: 10px; border-radius: 3px; font-family: monospace; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔒 Bandit Security Report</h1>
        <p><strong>Project:</strong> Universal BRC-20 Indexer</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
"""
    
    # Summary metrics
    metrics = data.get('metrics', {}).get('_totals', {})
    total_issues = len(data.get('results', []))
    
    html_content += f"""
    <div class="summary">
        <div class="metric">
            <h3>📊 Total Lines</h3>
            <p>{metrics.get('loc', 0):,}</p>
        </div>
        <div class="metric">
            <h3>🚨 Total Issues</h3>
            <p>{total_issues}</p>
        </div>
        <div class="metric">
            <h3>📁 Files Scanned</h3>
            <p>{len(data.get('metrics', {})) - 1}</p>
        </div>
    </div>
"""
    
    # Issues
    results = data.get('results', [])
    if results:
        html_content += "<h2>📋 Security Issues</h2>"
        for issue in results:
            severity = issue.get('issue_severity', 'UNKNOWN')
            confidence = issue.get('issue_confidence', 'UNKNOWN')
            test_name = issue.get('test_name', 'UNKNOWN')
            filename = issue.get('filename', 'UNKNOWN')
            line = issue.get('line_number', 'UNKNOWN')
            text = issue.get('issue_text', 'No description')
            code = issue.get('code', 'No code available')
            
            severity_class = f"severity-{severity.lower()}"
            
            html_content += f"""
    <div class="issue {severity_class}">
        <h3>{test_name}</h3>
        <p><strong>Severity:</strong> {severity} | <strong>Confidence:</strong> {confidence}</p>
        <p><strong>File:</strong> {filename}:{line}</p>
        <p><strong>Issue:</strong> {text}</p>
        <div class="code">{code}</div>
    </div>
"""
    else:
        html_content += """
    <div class="issue severity-low">
        <h3> No Security Issues Found</h3>
        <p>Congratulations! No security vulnerabilities were detected in the codebase.</p>
    </div>
"""
    
    html_content += """
</body>
</html>
"""
    
    with open(html_output_file, 'w') as f:
        f.write(html_content)
    
    print(f" HTML report generated: {html_output_file}")


def main():
    """Main function to run security scanning."""
    print(" Universal BRC-20 Indexer Security Scanner")
    print("=" * 50)
    
    # Create reports directory
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Run bandit scan with JSON output
    json_report_file = reports_dir / f"bandit_report_{timestamp}.json"
    print(f"\n Running Bandit security scan...")
    stdout, stderr, exit_code = run_bandit_scan("json", str(json_report_file))
    
    if exit_code == 0:
        print(" Bandit scan completed successfully")
    else:
        print(" Bandit scan completed with issues")
    
    # Analyze the report
    analyze_bandit_report(str(json_report_file))
    
    # Generate HTML report
    html_report_file = reports_dir / f"bandit_report_{timestamp}.html"
    generate_html_report(str(json_report_file), str(html_report_file))
    
    # Run text output for immediate viewing
    print(f"\n Detailed Bandit Output:")
    stdout, stderr, exit_code = run_bandit_scan("txt")
    print(stdout)
    
    print(f"\n Reports saved:")
    print(f"   JSON: {json_report_file}")
    print(f"   HTML: {html_report_file}")
    
    if exit_code == 0:
        print("\n Security scan completed successfully!")
        return 0
    else:
        print("\n  Security issues found. Please review the report above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())