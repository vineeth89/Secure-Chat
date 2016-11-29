import socket
import pickle
import hashlib
import DH,binascii
import sys,json,select
import zlib,os
from symetric import symetric
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding


class connection:
    '''
        Connection Object is a Singleton.
        Purpose : 1) Establish connection with server
                  2) Obtain shared secret with server
                  3) Request Server for user Keys

    '''
    def __init__(self,username,password):
        '''
            __init__(None) :
                Input   : None
                Output  : None
                Purpose : Constructor which initializes the Connection object
                          1) Reads The CLIENT.conf file and sets up essential variables
                          2) Reads the public_key.pem file and obtains the servers public key
                          3) Creates socket to talk to server
        '''
        self.__readConfigFile()
        self.__username = username
        self.__convertPasswordToSecret(password)
        self.__diffi = DH.DiffieHellman()
        self.__serverNonceHistory = {}
        self.__pubKey = self.__diffi.gen_public_key()

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except Exception as e:
            print "Error while creating socket",e
            sys.exit(0)

        with open("public_key.pem", "rb") as key_file:
            try:
                self.serverPublicKey = serialization.load_pem_public_key(
                    key_file.read(),
                    backend = default_backend())
            except Exception as e:
                print "Error while loading key ",e
                sys.exit(0)

    def getSock(self):
        return self.sock

    def __readConfigFile(self):
        ''' __readConfigFile(None) :
                   Input   : None
                   Output  : None
                   Purpose : Reads the CLIENT.conf file and extracts information from file
                             Information obtained include
                                   self.__salt       : Salt used to hash passwords
                                   self.__generator  : Generator used by Diffie Hellman
                                   self.__prime      : The Diffie Hellman Safe prime
        '''
        try:
            with open("CLIENT.conf", "rb") as conf_file:
                data = json.load(conf_file)
                self.__prime = data["prime"]
                self.__salt = data["salt"]
                self.__generator = data["generator"]

        except Exception as e:
            print "Error While reading Config File",e
            sys.exit(0)


    def __sendData(self,message,address = ('',2424)):
        ''' __sendData(String) :
                        Input   : String
                        Output  : None
                        Purpose : Sends the given String to the server
        '''
        try:
            self.sock.sendto(message, address)
        except Exception as e:
            print "Error while sending data",e

    def __recvData(self):
        ''' __recvData(None) :
                        Input   : None
                        Output  : None
                        Purpose : Receives data from the server once data becomes
                                    avilable on socket
        '''
        data = None
        while data is None:
            data = self.sock.recv(4096)
        data = pickle.loads(data)
        return data

    def __encryptMessageWithServerPubKey(self, message):
        ''' __encryptMessageWithServerPubKey(String) :
                        Input   : String
                        Output  : String (encrypted)
                        Purpose : Given a string encrypts the data with the servers
                                   Public Key and returns the encrypted data
       '''
        try:
            message = zlib.compress(message)
            cipherText = self.serverPublicKey.encrypt(
                message,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None))
        except Exception as e:
            print "Unable to perform asymetric encryption",e
            sys.exit(0)
        return cipherText


    def __sayHello(self):
        '''__sayHello(None) :
                    Input          : None
                    Output         : None
                    Purpose        : First step of Augmented string password protocol to inform server
                                     the client is now online and it requests to establish a shared
                                     secret
                    Message Format : { messageType :now-online,
                                        username
                                     }
        '''
        encodedObject = self.__encryptMessageWithServerPubKey(
                                    pickle.dumps({
                                        "user"          : self.__username,
                                        "messageType"   : "now-online",
                                    }))
        encodedObject = {
                "user"      : self.__username,
                "message"   : encodedObject,
                "type"      : "asym"
        }
        self.__sendData(pickle.dumps(encodedObject))

    def __puzzleSolve(self,data):
        ''' __puzzleSolve(String):
                Input  : String (The response from server when requested to initiate connection)
                Output :    Object -> { username ,
                                        S{user public key ,Computed Response to challenge},
                                        messageType
                                      }
                            False -> If the solution to challenge does not exist
        '''
        response = data["challange"]
        for x in range (-1,65537):
            sha = hashlib.sha256()
            sha.update(response+str(x))
            if sha.digest() == data["answer"]:
               message = pickle.dumps({
                   "answer"      : x,
                   "pubKey"      : self.__pubKey,
                   "messageType" : "quiz-response"
               })
               return pickle.dumps({
                   "user"       : self.__username,
                   "message"    : self.__encryptMessageWithServerPubKey(message),
                   "type"       : "asym"
               })
        return False

    def __convertPasswordToSecret(self,password):
        ''' __convertPasswordToSecret (String):
                           Input   : Password of User
                           Output  : None
                           Purpose : Converts test password to secret (2^w mod p)
                                     Once the secret is generated the passwords is forgotten
        '''
        sha = hashlib.sha256()
        sha.update(password + str(self.__salt))
        hash = sha.digest()
        hash = int(binascii.hexlify(hash), base=16)
        try :
            self.__passSecret = pow(self.__generator, hash, self.__prime)
        except Exception as e:
            print "Unable to convert password to secret ",e
        password = None


    def __establishSecret(self,data):
        """__establishSecret(String):
            Input   : String (Response from server with the for the sent response,
                      Contains servers public Key Diffie Hellman key
            Output  :
                        1) False if the hash sent does not match
                        2) Object containing sha384 of g^bw modp and g^ab
            Purpose : Verify the users password is correct and complete the password
                        authentication by sending the sha384 of g^bw modp and g
            Message Format :
                                {messageType: complete , user , hash }
        """
        serverPubKey = long(data["pubKey"])
        self.__sharedSecret = self.__diffi.gen_shared_key(serverPubKey)
        gpowbw =  self.__diffi.gen_gpowxw(serverPubKey,self.__passSecret)
        if self.__verifyPassword(gpowbw,self.__sharedSecret,long(data["hash"])) is False:
            return False
        hash = self.__gen384Hash(gpowbw,self.__sharedSecret)
        objToEnc = pickle.dumps({"messageType" : "complete", "hash" : hash})
        obj = {
            "user"      : self.__username,
            "message"   : self.__encryptMessageWithServerPubKey(objToEnc),
            "type"      : "asym"
        }
        self.__sharedSecret = str(self.__sharedSecret)[0:16]
        return pickle.dumps(obj)


    def __gen384Hash(self,gpowbw,sharedSecret):
        '''
            __gen384Hash(float,float) :
                    Input   : g^bw mod p , g^ab mod p
                    Output  : sha384(g^bw mod p + g^ab mod p)
                    Purpose :
                                Data used to determine at the server if the client has
                                the right password

        '''
        sha = hashlib.sha384()
        sha.update(str(gpowbw) + str(sharedSecret))
        hash = int(binascii.hexlify(sha.digest()), base=16)
        return hash

    def __verifyPassword(self,gpowbw,sharedSecret,serverHash):
        '''
            __verifyPassword(float,float,int) :
                Input   : g^bw mod p, g^ab mod p , sha256(g^bw mod p + g^ab mod p)
                Output  : None
                Purpose : Verify if the password enterd by the user matches that at the
                            server
        '''
        sha = hashlib.sha256()
        sha.update(str(gpowbw) + str(sharedSecret))
        hash = int(binascii.hexlify(sha.digest()), base=16)
        if hash  == serverHash:
            print "Login Success"
        else :
            print "Invalid username password please try again"
            return False

    def __listUsers(self):
        '''
            listUsers(None) :
                    Input  : None
                    Output : List (List of all users connected to the server)
                    Purpose : Gives the list of all users currently connected to server
        '''

        print type(self.__sharedSecret)
        iv = os.urandom(16)
        message  = self.__encryptSymetric(
            self.__sharedSecret,iv,
            pickle.dumps({"request" : "list",
                        "Nonce"     : str(int(binascii.hexlify(os.urandom(8)), base=16))
                    }))
        obj = {
            "user"      : self.__username,
            "message"   : message,
            "IV"        : iv,
            "type"      : "sym"
        }
        self.__sendData(pickle.dumps(obj))
        a = self.__recvData()
        message = self.__decryptSymetric(self.__sharedSecret,a["IV"],a["message"])
        message = pickle.loads(message)
        print "Message is ", message


    def __decryptSymetric(self,key,iv,message):
        '''
            __decryptSymetric(String,String):
                    Input  : String, String (The  Encryped message and the IV
                    Output : Decrypted message
                    Purpose : Decrypt message sent by server
        '''

        s = symetric(key)
        decryptor = s.getDecryptor(iv)
        return s.decrypt(message, decryptor)

    def __encryptSymetric(self,key,iv,message):
        '''
            __encryptSymetric(String,String):
                    Input  : String, String (The message to be Encryped and the IV
                    Output : Encrypted message with session key
                    Purpose : Encrypt message with session keys of client and server(Ksx)
        '''

        s = symetric(key)
        encryptor = s.getEncryptor(iv)
        return s.encryptMessage(message, encryptor)


    def establishConnection(self):
        ''''establishConnection(None) : Public method
                Input   : None
                Output  : None
                Purpose : Control to initial connection with server

        '''
        # Step 1 : Say Hello 
        self.__sayHello()
        data = self.__recvData()
        # Step 2 : Send Response to challange
        data = self.__puzzleSolve(data)
        self.__sendData(data)
        data = self.__recvData()
        # Step 3 : Generate Shared Secret and complete connection
        data = self.__establishSecret(data)
        if not data:
            return False
        self.__sendData(data)
        return True

    def __writeMessage(self,message):
        ''' __writeMessage(String)
                Input   : String (Message to be desplayed on console
                Output  : None
                Purpose : Print message on terminal
        '''
        sys.stdout.write(message)
        sys.stdout.flush()

    def __readFromConsole(self,message):
        '''
                __readFromConsole(String) :
                    Input   : Message to be printed on screen
                    Output  : The string entered on console
                    Purpose : Write a message on console and read from same
                '''
        self.__writeMessage(message)
        inputStreams = [sys.stdin]
        ready_to_read, ready_to_write, in_error = \
            select.select(inputStreams, [], [])
        msg = sys.stdin.readline()
        return msg.strip()


    def handleServerMessage(self):
        serverObj = self.__recvData()
        response = pickle.loads(self.__decryptSymetric(self.__sharedSecret,
                                                      serverObj["IV"],serverObj["message"]))
        if  "Nonce" in response and \
                        response["Nonce"] not in self.__serverNonceHistory:
            if response["message"] == "disconnect":
                print "Server just kicked you out"
                sys.exit(0)
            if response["message"] == "talkto":
                print "Ginga lala"

    def handleClientMessage(self,message):
        message = message.strip()
        if message == "list":
            self.__listUsers()
        if message == "talkto":
            self.__talkToHost()
        else:
            print "Unknown Message"

    def __talkToHost(self):
        destHost = self.__readFromConsole("Whom do you wish to speak to :")
        iv = os.urandom(16)
        obj = pickle.dumps({
            "user"    : destHost,
            "Nonce"     : str(int(binascii.hexlify(os.urandom(8)), base=16))
        })
        encryptedMessage = self.__encryptSymetric(self.__sharedSecret, iv, obj)
        self.__sendData(
            pickle.dumps({ "request": "talk",
                          "message" : encryptedMessage,
                          "IV"      : iv,
                          "type"    : "sym",
                          "user"    : self.__username,
                      }))
        message  = self.__recvData()
        message = pickle.loads(self.__decryptSymetric(self.__sharedSecret,message["IV"],message["message"]))

        self.__sendData(
                pickle.dumps({"message": message["ticket"], "IV": message["IV"] }),
            message["address"])