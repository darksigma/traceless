import hashlib
import random
import requests
import sys
import time
import thread
import json

from UST import *
from user import *

from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_PSS
from Crypto.Hash import SHA
from Crypto import Random

# Server Data
SERVER_URL = 'http://localhost:5000'

# Errors
ERROR = "Error"

# Constants
SUCCESS = "Success"
FAILED = "Failed"
TRUE = "True"
FALSE = "False"

# Routes
SERVER                          = 'server'
SUBSCRIBE                       = 'subscribe'
PUSH                            = 'push'
PULL                            = 'pull'
UPDATE_USER_TABLE               = 'update_user_table'
UPDATE_NEW_CONVERSATION_TABLE   = 'update_new_conversation_table'
INITIATE                        = 'initiate'
DELETE                          = 'delete'
RESERVE                         = 'reserve'

# Wait Times
NEW_CLIENT_WAIT         = 3.000     # Wait 3 seconds
NEW_CONVERSATION_WAIT   = 1.000     # Wait 1 second

class Client:

    def main(self,username):

        self.user_table = {}
        self.rsa = None
        self.rsa_sign = None

        self.username = username
        self.connect_server()
        self.subscribe()

        # Upon successfully suscribing begin updates
        self.updates()

        self.client_input()

    def connect_server(self):
        r = send_request(SERVER, {})
        self.server_pk_n = r['server_pk_n']
        self.server_pk_e = r['server_pk_e']

    def updates(self):
        try:
            thread.start_new_thread(self.client_update, ())
            thread.start_new_thread(self.conversation_update, ())
        except:
            print "ERRROR: unable to start client threads"
            print "FATAL: client unable to update"
            sys.exit(0)

    def client_input(self):
        while True:
            cmd = raw_input("Please enter a command: ")
            self.handle_input(cmd)

    def handle_input(self, cmd):
        parts = cmd.split(' ', 1)
        cmd_type = parts[0]

        if cmd_type == "1":
            self.print_user_table() 
        elif cmd_type == "2":
            cmd_args = parts[1]
            self.init_conversation(cmd_args)
        elif cmd_type == "3":
            cmd_args = parts[1]
            split = cmd_args.split(' ', 1)
            username = split[0]
            message = split[1] 
            self.send_message(username, message)
        elif cmd_type == "H":
            print "  1: 1 - Print Local User Table"
            print "  2: 2 <username> - Start Conversation with 'username'"
            print "  3: 3 <username> <message> - Send 'message' to 'username'"


    def print_user_table(self): 
        print "=== Local User Table ==="
        usernames = sorted(self.user_table.keys())
        for username in usernames:
            print "  %20s" % username
        print "\n",

    def subscribe(self):
        self.rsa = RSA_gen()
        self.n, self.e, self.d = RSA_keys(self.rsa)

        self.rsa_sign = RSA_gen()
        self.n_sign, self.e_sign, self.d_sign = RSA_keys(self.rsa_sign)

        self.ust = UST(self.server_pk_n, self.server_pk_e)
        self.ust.prepare()

        args = {"blinded_nonce"     :  self.ust.blinded_nonce, 
                "client_username"   :  self.username,
                "client_pk_n"       :  self.n, 
                "client_pk_e"       :  self.e,
                "client_sign_pk_n"  :  self.n_sign,
                "client_sign_pk_e"  :  self.e_sign}
        
        r = send_request(SUBSCRIBE, args)

        if r == ERROR:
            print "ERROR: could not subscribe"
            sys.exit(0)

        self.ust.receive(r['blinded_sign'])

        user = r['user']

        if user['client_pk_n'] == self.n and user['client_pk_e'] == self.e \
            and user['client_sign_pk_n'] == self.n_sign \
            and user['client_sign_pk_e'] == self.e_sign:
            pass
        else:
            print "Username is taken, please try again"
            sys.exit(0)

        self.user_id = user['client_user_id']
        self.user_table_ptr = 0

        return

    def client_update(self):
        while True:

            self.ust.prepare()

            args = {"nonce"                 :  self.ust.nonce,
                    "signature"             :  self.ust.signature,
                    "blinded_nonce"         :  self.ust.blinded_nonce, 
                    "client_user_table_ptr" :  self.user_table_ptr}

            r = send_request(UPDATE_USER_TABLE, args)
            
            self.ust.receive(r['blinded_sign'])

            new_users = r['new_users']

            for new_user in new_users:
                username = new_user['client_username']
                if username not in self.user_table:
                    user_id = new_user['client_user_id']
                    pk_n, pk_e, pk_sign_n, pk_sign_e = (new_user['client_pk_n'],
                                                       new_user['client_pk_e'],
                                                       new_user['client_sign_pk_n'],
                                                       new_user['client_sign_pk_e'])
                    user = User(username,user_id,pk_n,pk_e,pk_sign_n,pk_sign_e)
                    self.user_table[username] = user

                    self.user_table_ptr = user_id

            time.sleep(NEW_CLIENT_WAIT)
    	return

    def reserve_slot(self):
        while True:
            self.ust.prepare()

            slot_id = random.getrandbits(128) 
            nonce = (slot_id << 128) + random.getrandbits(128)
            ust_delete = UST(self.server_pk_n,self.server_pk_e)
            ust_delete.prepare(nonce)

            args = {"nonce"                     :  self.ust.nonce,
                    "signature"                 :  self.ust.signature,
                    "blinded_nonce"             :  self.ust.blinded_nonce, 
                    "slot_id"                   :  slot_id,
                    "blinded_deletion_nonce"    :  ust_delete.blinded_nonce}

            r = send_request(RESERVE, args)

            self.ust.receive(r['blinded_sign'])

            if r['success'] == True:
                ust_delete.receive(r['blinded_deletion_sign'])
                sig = ust_delete.signature
                return slot_id, sig

    def init_conversation(self, username):
        if username == self.username:
            print "ERROR: Please enter a username that is not your own"

        # Reserve Read/Write blocks
        read_block_id, read_block_sig = self.reserve_slot()
        write_block_id, write_block_sig = self.reserve_slot()

        P = (long(self.username.ljust(256))) << 384) + (long(username.ljust(username)) << 256) + \
            (read_block_id << 128) + write_block_id

        sign = PKCS1_sign(P, self.rsa_sign)
        rsa_recipient = RSA_gen_user(self.user_table[username])
        M = RSA_encrypt( (P << 512) + sign, rsa_recipient)

        self.ust.prepare()

        args = {"nonce"                     :  self.ust.nonce,
                "signature"                 :  self.ust.signature,
                "blinded_nonce"             :  self.ust.blinded_nonce, 
                "message"                   :  M}

        r = send_request(INITIATE, args)

        self.ust.receive(r['blinded_sign'])
        return 

    def conversation_update(self):
    	pass

    def send_message(self, username, message):
        pass

    def read_message(signature, ciphertext, other_user_public_key, my_key): #assumes other_user_public_key is tuple of form (n,e), my_key is of form (n,e,d)
        checksum_n = other_user_public_key[0]
        checksum_e = other_user_public_key[1]
        n = my_key[0]
        e = my_key[1]
        d = my_key[2]
        plaintext = RSA_decrypt(ciphertext, n, e, d)
        if PKCS1_verify(signature, plaintext, checksum_n, checksum_e) != True:
            return 'Message could not be verified'
        return plaintext

    def collect_messages(self):
    	pass

    def ust_update():
        new_nonce = random.getrandbits(2048)
        blinded_new_hash



def send_request(route, args):
    headers = {'content-type': 'application/json'}
    response = requests.post(SERVER_URL + "/" + route, headers=headers, data=json.dumps(args))
    if not (200 <= response.status_code < 300):
        raise Exception(response.text)
        return ERROR
    return json.loads(response.text)

def RSA_gen():
    return RSA.generate(2048)

def RSA_gen_user(user):
    return RSA.construct(user.pk_n,user.pk_e)

def RSA_keys(rsa):
    return rsa.n, rsa.e, rsa.d #returns RSA key object, n, e (both public) and secret key d

def RSA_encrypt(message, rsa): #takes in message, n, and e
    k = random.getrandbits(2048)
    return rsa.encrypt(message, k)

def RSA_decrypt(message, rsa):
    return rsa.decrypt(message)

def PKCS1_sign(message, rsa):
    h = SHA.new()
    h.update(message)
    signer = PKCS1_PSS.new(rsa)
    signature = signer.sign(h)
    return signature

def PKCS1_verify(signature, message, rsa):
    h = SHA.new()
    h.update(message)
    verifier = PKCS1_PSS.new(rsa)
    return verifier.verify(h, signature)

def H(m):
    """
   return hash (256-bit integer) of string m, as long integer.
   If the input is an integer, treat it as a string.
   """
    m = str(m)
    return int(hashlib.sha256(m).hexdigest(),16)

if len(sys.argv) < 2:
    print "ERROR: Please start client with an input username"
    sys.exit(0)

client = Client()
username_in = sys.argv[1]
client.main(username_in)
