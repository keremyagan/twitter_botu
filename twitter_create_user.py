from selenium import webdriver
import time 
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
from bs4 import BeautifulSoup
import requests




import json
import os
import pyperclip
import random
import requests
import string
import webbrowser

from random_username.generate import generate_username
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep
from typing import Dict


class Account:
    """Representing a temprary mailbox."""

    def __init__(self, id, address, password):
        self.id_ = id
        self.address = address
        self.password = password
        # Set the JWT
        jwt = MailTm._make_account_request("token",
                                           self.address, self.password)
        self.auth_headers = {
            "accept": "application/ld+json",
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(jwt["token"])
        }
        self.api_address = MailTm.api_address

    def get_messages(self, page=1):
        """Download a list of messages currently in the account."""
        r = requests.get("{}/messages?page={}".format(self.api_address, page),
                         headers=self.auth_headers)
        messages = []
        for message_data in r.json()["hydra:member"]:
            # recover full message
            r = requests.get(
                f"{self.api_address}/messages/{message_data['id']}", headers=self.auth_headers)
            text = r.json()["text"]
            html = r.json()["html"]
            # prepare the mssage object
            messages.append(Message(
                message_data["id"],
                message_data["from"],
                message_data["to"],
                message_data["subject"],
                message_data["intro"],
                text,
                html,
                message_data))
        
        return message_data["subject"]

    def delete_account(self):
        """Try to delete the account. Returns True if it succeeds."""
        r = requests.delete("{}/accounts/{}".format(self.api_address,
                                                    self.id_), headers=self.auth_headers)
        return r.status_code == 204

    def monitor_account(self):
        """Keep waiting for new messages and open them in the browser."""
        while True:
            print("\nWaiting for new messages...")
            start = len(self.get_messages())
            while len(self.get_messages()) == start:
                sleep(1)
            print("New message arrived!")
            self.get_messages()[0].open_web()


@dataclass
class Message:
    """Simple data class that holds a message information."""
    id_: str
    from_: Dict
    to: Dict
    subject: str
    intro: str
    text: str
    html: str
    data: Dict

    def open_web(self):
        """Open a temporary html file with the mail inside in the browser."""
        with NamedTemporaryFile(mode="w", delete=False, suffix=".html") as f:

            html = self.html[0].replace("\n", "<br>").replace("\r", "")
            message = """<html>
            <head></head>
            <body>
            <b>from:</b> {}<br>
            <b>to:</b> {}<br>
            <b>subject:</b> {}<br><br>
            {}</body>
            </html>""".format(self.from_, self.to, self.subject, html)

            f.write(message)
            f.flush()
            file_name = f.name

            open_webbrowser("file://{}".format(file_name))
            # Wait a second before deleting the tempfile, so that the
            # browser can load it safely
            sleep(1)
            #  os.remove(file_name)


def open_webbrowser(link: str) -> None:
    """Open a url in the browser ignoring error messages."""
    saverr = os.dup(2)
    os.close(2)
    os.open(os.devnull, os.O_RDWR)
    try:
        webbrowser.open(link)
    finally:
        os.dup2(saverr, 2)


class CouldNotGetAccountException(Exception):
    """Raised if a POST on /accounts or /authorization_token return a failed status code."""


class InvalidDbAccountException(Exception):
    """Raised if an account could not be recovered from the db file."""


class MailTm:
    """A python wrapper for mail.tm web api, which is documented here:
       https://api.mail.tm/"""

    api_address = "https://api.mail.tm"
    db_file = os.path.join(Path.home(), ".pymailtm")

    def _get_domains_list(self):
        r = requests.get("{}/domains".format(self.api_address))
        response = r.json()
        domains = list(map(lambda x: x["domain"], response["hydra:member"]))
        return domains

    def get_account(self, password=None):
        """Create and return a new account."""
        username = (generate_username(1)[0]).lower()
        domain = random.choice(self._get_domains_list())
        address = "{}@{}".format(username, domain)
        if not password:
            password = self._generate_password(6)
        response = self._make_account_request("accounts", address, password)
        account = Account(response["id"], response["address"], password)
        self._save_account(account)
        return account

    def _generate_password(self, length):
        letters = string.ascii_letters + string.digits
        return ''.join(random.choice(letters) for i in range(length))

    @staticmethod
    def _make_account_request(endpoint, address, password):
        account = {"address": address, "password": password}
        headers = {
            "accept": "application/ld+json",
            "Content-Type": "application/json"
        }
        r = requests.post("{}/{}".format(MailTm.api_address, endpoint),
                          data=json.dumps(account), headers=headers)
        if r.status_code not in [200, 201]:
            raise CouldNotGetAccountException()
        return r.json()

    def monitor_new_account(self, force_new=False):
        """Create a new account and monitor it for new messages."""
        account = self._open_account(new=force_new)
        account.monitor_account()

    def _save_account(self, account: Account):
        """Save the account data for later use."""
        data = {
            "id": account.id_,
            "address": account.address,
            "password": account.password
        }
        with open(self.db_file, "w+") as db:
            json.dump(data, db)

    def _load_account(self):
        """Return the last used account."""
        with open(self.db_file, "r") as db:
            data = json.load(db)
        # send a /me request to ensure the account is there
        if "address" not in data or "password" not in data or "id" not in data:
            # No valid db file was found, raise
            raise InvalidDbAccountException()
        else:
            return Account(data["id"], data["address"], data["password"])

    def _open_account(self, new=False):
        """Recover a saved account data, check if it's still there and return that one; otherwise create a new one and 
        return it.
        :param new: bool - force the creation of a new account"""
        def _new():
            account = self.get_account()
            print("New account created and copied to clipboard: {}".format(account.address), flush=True)
            return account
        if new:
            account = _new()
        else:
            try:
                account = self._load_account()
                print("Account recovered and copied to clipboard: {}".format(account.address), flush=True)
            except Exception:
                account = _new()
        pyperclip.copy(account.address)
        print("")
        return account,account.address

    def browser_login(self, new=False):
        """Print login credentials and open the login page in the browser."""
        account = self._open_account(new=new)
        print("\nAccount credentials:")
        print("\nEmail: {}".format(account.address))
        print("Password: {}\n".format(account.password))
        open_webbrowser("https://mail.tm/")
        sleep(1)  # Allow for the output of webbrowser to arrive
        


options = webdriver.ChromeOptions()
options.add_argument('--lang=tr')


#create new account
path="chromedriver.exe"
lower = string.ascii_lowercase
upper = string.ascii_uppercase
num = string.digits
symbols = string.punctuation
all = lower + upper + num + symbols
while True:
    try:      
        aylar_1=["O","K","A","E","T","MM","EE","AA","Ş","N","H","M"]#rastgele bir ay seçilir
        gunler=random.randint(1,28)#aylar içerisinde en az 28 gün bulunduğu için en fazla 28 seçilir
        yillar=random.randint(1940,2000)#1940-2000 arası rastgele bir yıl seçilir
        aylar=random.choice(aylar_1)  
        username=generate_username()#rastgele kullanıcı adı oluşturulur
        temp = random.sample(all,10)
        if ":" in temp:
            temp.remove(":")
        password = "".join(temp)
        mail=MailTm()
        mail_1=mail._open_account(True)#yeni mail adresi açılır
        email_address=mail_1[1]
        driver=webdriver.Chrome(executable_path=path, chrome_options=options)
        url="https://twitter.com/i/flow/signup"
        driver.get(url)
        time.sleep(3)
        to_email=driver.find_element_by_xpath('//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[2]/div/div/div[4]')
        to_email.send_keys(Keys.ENTER)
        time.sleep(3)
        name=driver.find_element_by_name("name")
        email=driver.find_element_by_name("email")
        month=driver.find_element_by_xpath('//*[@id="Ay"]')
        day=driver.find_element_by_xpath('//*[@id="Gün"]')
        year=driver.find_element_by_xpath('//*[@id="Yıl"]')
        name.send_keys(username)
        email.send_keys(email_address)
        month.send_keys(aylar)
        year.send_keys(str(yillar))
        day.send_keys(str(gunler))
        next_step=driver.find_element_by_xpath('//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[1]/div/div/div/div[3]/div/div/span')
        ActionChains(driver).click(next_step).perform()
        time.sleep(3)
        next_step2=driver.find_element_by_xpath('//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[1]/div/div/div/div[3]/div/div/span')
        ActionChains(driver).click(next_step2).perform()
        time.sleep(3)
        next_step2=driver.find_element_by_xpath('//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[1]/div/div/div/div[3]/div/div/span')
        ActionChains(driver).click(next_step2).perform()
        time.sleep(3)
        next_step3=driver.find_element_by_xpath('//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[2]/div/div/div/div[5]')
        ActionChains(driver).click(next_step3).perform()
        account_details=mail_1[0]
        time.sleep(7)
        account=Account(account_details.id_,account_details.address,account_details.password)
        get_message=account.get_messages()#onay maili alınır
        confirm_code=get_message.split()[3]
        verification_input=driver.find_element_by_name("verfication_code")
        verification_input.send_keys(confirm_code)
        next_step4=driver.find_element_by_xpath('//*[@id="layers"]/div/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[1]/div/div/div/div[3]/div/div/span')
        ActionChains(driver).click(next_step4).perform()
        time.sleep(4)
        password_input=driver.find_element_by_name("password")
        password_input.send_keys(password)
        time.sleep(1)
        next_step5=driver.find_element_by_xpath('//*[@id="layers"]/div/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[1]/div/div/div/div[3]/div/div/span')
        ActionChains(driver).click(next_step5).perform()
        file=open("twitter.txt","a")#bilgiler dosya içerisine eklenir
        file.write(f"{email_address}:{password}:{account_details.id_}:{account_details.address}:{account_details.password}\n")
        file.close()
        next_step6=driver.find_element_by_xpath('//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[1]/div/div/div/div[3]/div/div/span')
        ActionChains(driver).click(next_step6).perform()
        time.sleep(2)
    except Exception as err:
        print(err)
        time.sleep(1)
        driver.close()
     
  
   
    
    
    




