import os
import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2, aws_iam as iam, aws_s3_assets as s3_assets
from constructs import Construct


class ReportsBotStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # ── Upload app code to S3 ─────────────────────────────────────────────
        app_asset = s3_assets.Asset(
            self, "AppCode",
            path=os.path.join(os.path.dirname(__file__), ".."),
            exclude=[
                # never ship secrets or local dev state
                ".env",
                # CDK and build artifacts
                "cdk_deploy", "cdk.out", "__pycache__", "*.pyc",
                # version control
                ".git", ".gitignore",
                # virtualenvs
                "venv", ".venv",
                # runtime-generated (rebuilt on first query)
                "chroma_db", "data/chroma_db",
                # logs and caches
                "*.log", "*.jsonl",
                "data/confluence_cache",
                ".pytest_cache",
                # Windows artifacts
                "Thumbs.db", "desktop.ini",
            ],
        )

        # ── IAM role ──────────────────────────────────────────────────────────
        role = iam.Role(
            self, "Ec2Role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ],
        )

        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=["arn:aws:secretsmanager:us-east-1:<aws-account-id>:secret:idre/reports-bot/secrets*"],
        ))
        app_asset.grant_read(role)

        # ── VPC + Security group ──────────────────────────────────────────────
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        sg = ec2.SecurityGroup(self, "Sg", vpc=vpc, allow_all_outbound=True, description="IDRE Reports Bot")
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(8501), "Streamlit")
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "SSH")

        # ── EC2 instance ──────────────────────────────────────────────────────
        instance = ec2.Instance(
            self, "Ec2",
            instance_type=ec2.InstanceType("t3.medium"),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=sg,
            role=role,
            instance_name="idre-reports-bot",
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(30)
                )
            ],
        )

        # ── Startup script ────────────────────────────────────────────────────
        script = f"""#!/bin/bash
set -e
exec > /var/log/idre-setup.log 2>&1

echo "=== Installing system packages ==="
dnf update -y
dnf install -y python3 python3-pip gcc unzip

echo "=== Downloading app from S3 ==="
aws s3 cp s3://{app_asset.s3_bucket_name}/{app_asset.s3_object_key} /tmp/app.zip
mkdir -p <HOME>/app
unzip -o /tmp/app.zip -d <HOME>/app

echo "=== Fetching secrets and writing .env ==="
cat << 'PYEOF' > /tmp/fetch_secrets.py
import subprocess
import json
import sys

try:
    res = subprocess.check_output([
        'aws', 'secretsmanager', 'get-secret-value',
        '--secret-id', 'idre/reports-bot/secrets',
        '--region', 'us-east-1',
        '--query', 'SecretString',
        '--output', 'text'
    ])
    secret_str = res.decode('utf-8').strip()

    try:
        data = json.loads(secret_str)
    except Exception:
        import re
        data = {{}}
        for m in re.finditer(r'"?(\w+)"?\s*:\s*"?([^",}}]+)"?', secret_str):
            data[m.group(1).strip()] = m.group(2).strip()

    gemini  = data.get('gemini_api_key', '')
    db_pass = data.get('db_password', '')
    app_pw  = data.get('app_password', 'IDRE_RB_135679')

    with open('<HOME>/app/.env', 'w') as f:
        f.write(f"Gemini_API_Key=<redacted>")
        f.write("DB_HOST=<rds-endpoint>\\n")
        f.write("DB_PORT=3306\\n")
        f.write("DB_NAME=idre_stage\\n")
        f.write("DB_USER=app_idre_rw\\n")
        f.write(f"DB_PASSWORD=<redacted>")
        f.write("DB_SSL_CA=./global-bundle.pem\\n")
        f.write(f"APP_PASSWORD=<redacted>")

    print("Successfully wrote .env file.")
except Exception as e:
    print(f"Failed to fetch secrets: {{e}}", file=sys.stderr)
    sys.exit(1)
PYEOF

python3 /tmp/fetch_secrets.py

echo "=== Installing Python dependencies ==="
cd <HOME>/app
python3 -m venv <HOME>/app/venv
<HOME>/app/venv/bin/python -m pip install --upgrade pip
<HOME>/app/venv/bin/python -m pip install -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

echo "=== Ensuring data directories exist ==="
mkdir -p <HOME>/app/data/chroma_db
mkdir -p <HOME>/app/data/confluence_cache

echo "=== Setting file permissions ==="
chown -R ec2-user:ec2-user <HOME>/app

echo "=== Creating systemd service ==="
cat > /etc/systemd/system/streamlit.service << 'EOF'
[Unit]
Description=IDRE Reports Bot (Streamlit)
After=network.target

[Service]
User=ec2-user
WorkingDirectory=<HOME>/app
ExecStart=<HOME>/app/venv/bin/python -m streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false
Restart=always
RestartSec=10
Environment=HOME=<HOME>
Environment=PATH=/usr/local/bin:/usr/bin:/bin
StandardOutput=journal
StandardError=journal
EOF

systemctl daemon-reload
systemctl enable streamlit
systemctl start streamlit

echo "=== Setup complete ==="
echo "App running at http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8501"
"""
        instance.add_user_data(script)

        # ── Outputs ───────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "PublicIp",   value=instance.instance_public_ip)
        cdk.CfnOutput(self, "AppUrl",     value=f"http://{instance.instance_public_ip}:8501")
        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
