#!/usr/bin/env python
import aws_cdk as cdk
from stack import ReportsBotStack

app = cdk.App()
ReportsBotStack(app, "idre-reports-bot", env=cdk.Environment(account="<aws-account-id>", region="us-east-1"))
app.synth()
