import os,sys,DH,pickle,binascii
import hashlib,zlib,json
from Auth import Auth
from symetric import symetric
from random import randint
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

class Connection:
    '''
        Provides adapter interfaces to Server Object
        Identifies the type of incoming  message and on the socket
         and generates appropriate response to send to client
         Provides augmented strong password authentication
    '''
    def __init__(self):
        '''
           __init__(None):
                Input  : None
                Output : None
                Purpose : 1) Initialise Connection object
                          2) Read server private key for future use
        '''
        self.__diffiObj = DH.DiffieHellman()
        self.__authDict      = {}
        self.__sessionKeyDict = {}
        self.__userNonceHistor = {}
        with open("private_key.pem", "rb") as key_file:
            try:
                self.__privateKey = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend())
            except:
                print "Error while Loading key " + file
                sys.exit(0)
        
    def getSessionKeys(self):
        '''
            getSessionKeys(None):
                Input   : None
                Output  : Object
                Purpose : Returns the session key of all clients authenticated
                            with server
        '''
        return self.__sessionKeyDict

    def __nowOnlineResponse(self, senderObj, address):
        '''
            __nowOnlineResponse(None):
                Input  : None
                Output : Obj { }
                Message format
                    {"message-type":"quiz", challange, hash{answer}}
                Purpose : When Client shows intent to connect Generate a challenge
                            and send it to server
        '''

        if senderObj["user"] in self.__authDict:
            self.__authDict.pop(senderObj["user"])
        rand = os.urandom(100)
        t = randint(30000,65536)
        sha = hashlib.sha256()
        sha.update(rand+str(t))
        guess = sha.digest()
        self.__authDict[senderObj["user"]] = Auth(str(t))
        response =  [ pickle.dumps({
                "message-type"  : "quiz",
                "challange"     : rand,
                "answer"        : guess
             }), address]
        return response

    def __findPasswordHashForUser(self, user):
        '''
            __findPasswordHashForUser(String):
                Input   :   (String) UserName
                Output  :   False  -> If username not found
                            String -> Password hash
                Purpose :   Given a username searches if the user is registerd
                            and returns the username
        '''
        with open("SERVER.conf") as json_file:
            json_data = json.load(json_file)
            if user.lower() in json_data:
                return json_data[user.lower()]
            else :
                return False
            
    def __challangeResponse(self, senderObj, address):
        '''
            __challangeResponse(Object):
            Input  : Object {messageType:"quiz-response", encoded } (Response from server to challenge)
                            encoded -> {g^a mod p,response}s
            Output : String
            Message format :
                        {messageType:"initiageSecret", sha256(g^ab mod p + g^bw mod p), g^b mod p}
            Purpose : Send server public secret and augmented information

        '''
        response = [False, address]
        if senderObj["user"] in self.__authDict:
            authInfo = self.__authDict[senderObj["user"]]
            if authInfo.getQuizz() == str(senderObj["answer"]):
                response =  self.__challangeResponseHelper(senderObj, authInfo, address)
            else :
                self.__authDict.pop(senderObj["user"])
        return response

    def __challangeResponseHelper(self, senderObj, authInfo, address):
        '''
            __challangeResponseHelper(Object,Object):
                    Input   : The  Objectified stream data from user
                                and Authentication info on server
                    Output : String (Data to be send on wire)
                     Message format :
                        {messageType:"initiageSecret", sha256(g^ab mod p + g^bw mod p), g^b mod p}

        '''
        response = [False, address]
        pubKey = self.__diffiObj.gen_public_key()                                 # This is (gb mod p)
        sharedSecret = self.__diffiObj.gen_shared_key(long(senderObj["pubKey"]))  # This is (gab mop p)
        authInfo.setResponse()
        authInfo.setSharedSecret(str(sharedSecret)[0:16])
        userPassHash = self.__findPasswordHashForUser(senderObj["user"])
        if userPassHash:
            gpowbw = self.__diffiObj.gen_gpowxw(pubKey, userPassHash)
            hash256 = self.__genShaX(hashlib.sha256(),str(gpowbw) + str(sharedSecret))
            hash384 = self.__genShaX(hashlib.sha384(),str(gpowbw) + str(sharedSecret))
            authInfo.setSha348(hash384)
            response =  [pickle.dumps({
                "messageType": "initiateSecret",
                "hash": hash256,
                "pubKey": pubKey,
            }), address]
        return response

    def __genShaX(self, sha, message):
        '''
            __genShaX(Object,String):
                    Input   : Object,Strint (THe sha object ie.sha256,384,512 and the message
                                            to be encrypted)
                    Output  : String (Returns the digest of the message)

        '''
        sha.update(message)
        return int(binascii.hexlify(sha.digest()), base=16)

    def __decryptMessageUsingPrivateKey(self, message):
        '''
            __decryptMessageUsingPrivateKey(String):
                    Input   : String
                    Output  : String
                    Purpose : Decrypt data encrypted with server public key

        '''
        try:
            plainText = self.__privateKey.decrypt(
                message,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None))
        except Exception as e:
            print "Unable to perform asymmetric decryption",e
            sys.exit(0)
        return zlib.decompress(plainText)

    def __logErrors(self,errTime,address):
        '''
            __logErrors(String,tupple):
                Input   : String , Tupple(address)
                Output  : None
                Purpose : Log errors on console

        '''
        print "There was an error during " + errTime + " from host"+ str(address)

    def __gen384Hash(self, gpowbw, sharedSecret):
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

    def __disconnectUser(self, user):
        '''
        __disconnectUser(String) : User Name to be disconnected
            Input   : String
            Output  : None
            Purpose : Remove user connection
        '''
        userDetails = self.__sessionKeyDict[user]
        print "Kicking out user " + user + " on ",userDetails[1]
        iv = os.urandom(16)
        message = self.__encryptSymetric(
            user,
             pickle.dumps(
                 { "message" : "disconnect",
                   "Nonce": str(int(binascii.hexlify(os.urandom(8)), base=16))
                }),iv)
        self.__sessionKeyDict.pop(user)
        return [pickle.dumps({
            "message": message,
            "IV": iv
        }), userDetails[1]]

    def __addUserToAuthDict(self, senderObj, address):
        '''
        __addUserToAuthDict(Object,tupple)
        '''
        response = [True, address]
        if senderObj["user"] in self.__sessionKeyDict:
            response = self.__disconnectUser(senderObj["user"])
        self.__sessionKeyDict[senderObj["user"]] = [
            self.__authDict[senderObj["user"]].getSharedSecret(),
            address]
        self.__authDict.pop(senderObj["user"])
        return response

    def __completeAuth(self, senderObj, address):
        '''
            __completeAuth(Object,tupple) :
                Input  : Object,tupple (The sender Objectified stream data from user
                                and Authentication info on server)
                Output : Tupple
        '''
        response = [True, address]
        if senderObj["user"] in self.__authDict:
            if senderObj["hash"] == self.__authDict[senderObj["user"]].getSha384():
                print "User " + senderObj["user"] + " Connected"
                response = self.__addUserToAuthDict(senderObj, address)
            else :
                self.__authDict.pop(senderObj["user"])
        return response

    def __loadPickledData(self, message):
        '''
            __loadPickledData(String):
                Input  : String (Stream data from socket)
                Output : Object
                Purpose : Convert the stream data to object
        '''
        try:
            return pickle.loads(message)
        except Exception as e:
            print "Error while trying to unpickle data ",e
            return False

    def __parseStreamData(self, senderObj):
        '''
            __parseStreamData(String):
                Input   : String (Data on sock stream)
                Output  : Obj
                Purpose : Given the data sent by the client on the wire
                            the data is unpickled, decrypted and converted
                             into object for further use
        '''
        decryptedResponse = self.__decryptMessageUsingPrivateKey(senderObj["message"])
        decryptedResponse = self.__loadPickledData(decryptedResponse)
        decryptedResponse["user"] = senderObj["user"]
        return decryptedResponse

    def __newConnection(self, senderObj, address):
        '''
            newConnection(Object,tupple) :
                Input   : Object,tupple (Objectified data from sock and address)
                Output  : String (data to be sent to server
                Purpose : Parses the incoming message and  generate appropriate response
                            to send to client. Used to establish new connection with client
        '''
        response = False
        decryptedMessage = self.__parseStreamData(senderObj)
        if decryptedMessage["messageType"] == "now-online":
            response = self.__nowOnlineResponse(decryptedMessage,address)
        elif decryptedMessage["messageType"] == "quiz-response":
            response = self.__challangeResponse(decryptedMessage,address)
        elif decryptedMessage["messageType"] == "complete":
            response = self.__completeAuth(decryptedMessage,address)
        return response

    def __listUsers(self, senderObj,address):
        '''
            __listUsers(None):
                Input  : None
                Output : Array string of list of all users connected to
                        server
        '''
        response = [False, address]
        message = senderObj["message"]
        if message["Nonce"] not in self.__userNonceHistor :
            self.__userNonceHistor[message["Nonce"]] = True
            iv = os.urandom(16)
            message = self.__encryptSymetric( senderObj["user"],
                pickle.dumps({"users":self.__sessionKeyDict.keys(),"Nonce":int(message["Nonce"])+1}),iv
            )
            response =[pickle.dumps({
                    "message": message,
                    "IV":iv
                }), address]
        return response

    def __encryptSymetric(self, user, message, iv):
        '''
            __encryptSymetric(String,String):
                    Input  : String, String (The message to be Encryped and the IV
                    Output : Encrypted message with session key
                    Purpose : Encrypt message with session keys of client and server(Ksx)
        '''

        s = symetric(self.__sessionKeyDict[user][0])
        encryptor = s.getEncryptor(iv)
        return s.encryptMessage(message, encryptor)


    def __genKeyPair(self, senderObj, address):
        '''
            __genKeyPair():
        '''
        encMessage = senderObj["message"]
        if senderObj["user"] in self.__sessionKeyDict \
                and encMessage["user"] in self.__sessionKeyDict:

            if encMessage["Nonce"] in self.__userNonceHistor:
                return [False, address]
            iv = os.urandom(16)
            key = os.urandom(16)
            ivin = os.urandom(16)

            # Generate Token for B
            token = self.__encryptSymetric(
                encMessage["user"],pickle.dumps({
                    "Key"       : key,
                    "Nonce"     : str(int(binascii.hexlify(os.urandom(8)), base=16)),
                    "message"   : "talkto",
                    "user"   : [senderObj["user"], self.__sessionKeyDict[senderObj["user"]][1]]
                }),
                ivin)
            # Encrypt Ticket and key to send to sender
            encMessage = self.__encryptSymetric(senderObj["user"] ,
                                    pickle.dumps({
                                        "key": key,
                                        "Nonce": str(int(binascii.hexlify(os.urandom(8)), base=16)),
                                        "ticket": token,
                                        "IV" :ivin,
                                        "address": self.__sessionKeyDict[encMessage["user"]][1]
                                    }), iv)

            return [ pickle.dumps({
                "message": encMessage,
                "IV": iv
            }), address]
        else:
            return [False, address]


    def __establishedConnection(self, senderObj, address):
        '''
             __establishedConnection(Object):
                    Input   : Object (Objectified data from sock )
                    Output  :
                    Purpose :
        '''
        user = senderObj["user"]
        if user not in self.__sessionKeyDict:
            return False
        s = symetric(self.__sessionKeyDict[user][0])
        decryptor = s.getDecryptor(senderObj["IV"])
        senderObj["message"] = pickle.loads (
            s.decrypt(senderObj["message"],decryptor)
        )
        if senderObj["message"]["request"] == "list":
            return self.__listUsers(senderObj, address)
        if senderObj["message"]["request"] == "talk":
            return self.__genKeyPair(senderObj, address)



    def parseData(self, data, address):
        '''
            _parseData(String,tupple):
                    Input   : String,tupple (Input from socket and incoming address)
                    Output  : None
                    Purpose : Calls the appropriate method based on if the request is
                                from a already authenticated client or if it is from
                                a client requesting a new connection
        '''
        unPickledData = self.__loadPickledData(data)
        if unPickledData["type"] == "sym":
            return self.__establishedConnection(unPickledData,address)
        else :
            return self.__newConnection(unPickledData,address)