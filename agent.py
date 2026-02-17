import requests
import paramiko
import time

BACKEND = "https://src-qty-telephony-hearings.trycloudflare.com/"


def run_ssh(ip, username, password, command):

    try:

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh.connect(
            ip,
            username=username,
            password=password,
            timeout=10
        )

        stdin, stdout, stderr = ssh.exec_command(command)

        output = stdout.read().decode()
        error = stderr.read().decode()

        ssh.close()

        return output + error

    except Exception as e:
        return str(e)


def main():

    print("Agent started...")

    while True:

        try:

            r = requests.get(f"{BACKEND}/api/agent/jobs")

            jobs = r.json()

            for job in jobs:

                print("Running job:", job["_id"])

                output = run_ssh(
                    job["ip"],
                    job["username"],
                    job["password"],
                    job["command"]
                )

                requests.post(
                    f"{BACKEND}/api/agent/result",
                    json={
                        "job_id": job["_id"],
                        "output": output
                    }
                )

        except Exception as e:

            print("Error:", e)

        time.sleep(5)


if __name__ == "__main__":
    main()
