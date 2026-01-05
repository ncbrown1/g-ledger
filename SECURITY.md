# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in G-Ledger, please report it by emailing [your-security-email@example.com] or opening a private security advisory on GitHub.

**Please do not report security vulnerabilities through public GitHub issues.**

### What to Include

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Fix & Disclosure**: Coordinated with reporter

## Security Best Practices

### Protecting Your Credentials

1. **Never commit secrets to git**
   - `config.yaml` and `service-account-key.json` are in `.gitignore`
   - Use environment variables for CI/CD

2. **Google Service Account Security**
   - Restrict service account permissions to minimum required
   - Enable Google Sheets API only
   - Use domain-wide delegation sparingly
   - Rotate keys periodically

3. **SimpleFIN Credentials**
   - Store SimpleFIN tokens securely
   - Use Setup Token only once, then delete
   - Access Tokens should be treated as passwords

4. **File Permissions**
   ```bash
   chmod 600 config.yaml
   chmod 600 service-account-key.json
   ```

### Google Sheets Permissions

Required Google Sheets API scopes:
- `https://www.googleapis.com/auth/spreadsheets` (read/write)

**Recommended sheet permissions:**
- Make service account an editor
- Restrict sheet sharing to authorized users only
- Enable 2FA for all users with access

### Data Privacy

- G-Ledger processes financial data locally
- Data is synced to your Google Sheet (ensure proper access controls)
- Snapshot repository contains full transaction history
- No telemetry or data sent to third parties

## Known Security Considerations

1. **Service Account Key**: Stored as JSON file on disk
   - Risk: If compromised, attacker can access your sheet
   - Mitigation: Use file permissions, secure host

2. **SimpleFIN Credentials**: Stored in config.yaml
   - Risk: If compromised, attacker can access bank data
   - Mitigation: Use file permissions, secure host

3. **Google Sheets**: Contains all financial data
   - Risk: Overly permissive sharing
   - Mitigation: Limit sharing, audit access logs

## Dependency Security

Run regular security audits:
```bash
pip install safety
safety check -r requirements.txt
```

Or use GitHub's Dependabot (recommended).
