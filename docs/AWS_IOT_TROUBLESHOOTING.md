# AWS IoT Core Troubleshooting Guide

## Error: "AWS IoT Core closed connection (code: 128)"

This error occurs when AWS IoT Core forcibly closes the MQTT connection, usually due to policy permission issues.

### Common Causes

1. **Missing IoT Policy Permissions**
   - The certificate's IoT policy doesn't allow publishing to your topic
   - Solution: Update the policy to allow `iot:Publish` action

2. **Duplicate Client ID**
   - Another device is connected with the same `client_id`
   - Solution: Use unique client IDs or disconnect the other client

3. **Certificate Not Attached to Policy**
   - The certificate exists but has no policy attached
   - Solution: Attach the policy to your certificate in AWS Console

### How to Fix the Policy

#### Option 1: AWS Console (Recommended)

1. Go to AWS IoT Console: https://console.aws.amazon.com/iot/
2. Navigate to **Security** > **Policies**
3. Find or create a policy for your certificate
4. Ensure it includes these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:eu-west-3:*:client/molleaumetre-client"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": "arn:aws:iot:eu-west-3:*:topic/molleaumetre/*"
    }
  ]
}
```

5. Navigate to **Security** > **Certificates**
6. Find your certificate: `f230f8129daf75a0bc6fc63b44c1e998bee5b53e116e429d03990a12d3a71917`
7. Click **Attach Policy** and select your policy
8. Verify certificate status is **Active**

#### Option 2: AWS CLI

```bash
# 1. Create the policy (if it doesn't exist)
aws iot create-policy \
  --policy-name molleaumetre-policy \
  --policy-document file://docs/aws-iot-policy-example.json \
  --region eu-west-3

# 2. Attach policy to your certificate
aws iot attach-policy \
  --policy-name molleaumetre-policy \
  --target arn:aws:iot:eu-west-3:YOUR_ACCOUNT_ID:cert/f230f8129daf75a0bc6fc63b44c1e998bee5b53e116e429d03990a12d3a71917 \
  --region eu-west-3

# 3. Verify certificate is active
aws iot describe-certificate \
  --certificate-id f230f8129daf75a0bc6fc63b44c1e998bee5b53e116e429d03990a12d3a71917 \
  --region eu-west-3
```

### Testing the Fix

After updating your policy, run the gateway again:

```bash
./ble_gateway.py -c config.json --log-level INFO
```

You should see:
```
Successfully connected to MQTT broker
```

And NO disconnection errors.

### AWS IoT Policy Best Practices

1. **Use wildcard topics for flexibility:**
   ```json
   "Resource": "arn:aws:iot:REGION:*:topic/molleaumetre/*"
   ```

2. **Restrict by client ID for security:**
   ```json
   "Resource": "arn:aws:iot:REGION:*:client/molleaumetre-client"
   ```

3. **Don't use `*` for everything in production:**
   ```json
   "Resource": "*"  // ❌ Too permissive!
   ```

### Monitoring AWS IoT

Enable CloudWatch Logs for AWS IoT to see detailed connection logs:

1. AWS IoT Console > **Settings**
2. Enable **Logs**
3. Set log level to **Info** or **Debug**
4. View logs in CloudWatch Logs

### Still Having Issues?

Check these:

1. **Certificate is active:**
   - AWS IoT Console > Security > Certificates
   - Status should be "Active"

2. **Thing is attached to certificate:**
   - Not required for basic pub/sub, but recommended

3. **No conflicting policies:**
   - Only one policy should be attached
   - Check for "Deny" statements

4. **Endpoint is correct:**
   - Should be: `xxxxxxxx-ats.iot.REGION.amazonaws.com`
   - Port: `8883` (MQTT over TLS)

5. **Certificates are valid:**
   - Check expiration dates
   - Verify file paths in `config.json`
