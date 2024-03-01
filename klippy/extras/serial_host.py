import logging
import time

class SerialHost:
    def __init__(self, config):
        self.config = config
        self.printer = config.get_printer()
        self.mutex = self.printer.get_reactor().mutex()
        self.reactor = self.printer.get_reactor()
        self._logging = config.getboolean("logging", True)
        self._last_message = None
        self._last_gcode_output = ""
        self._gcode_callbacks = {}

        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_output_handler(self.gcode_output_handler)
        bridge = config.get('serial_bridge')
        self.serial_bridge = self.printer.lookup_object(
            'serial_bridge %s' %(bridge))
        self.serial_bridge.register_callback(
            self._handle_serial_bridge_response)
        # self._update_timer = self.reactor.register_timer(self._screen_update)
        return
    
    def handle_ready(self):
        for n in self.printer.lookup_objects():
            self.log(f"object: {n}" )
        return

    def _handle_serial_bridge_response(self, data):
        byte_debug = ' '.join(['0x{:02x}'.format(byte) for byte in data])
        self.log("R: " + byte_debug)
        completed_messages = []
        message = self._last_message if self._last_message else None

        for byte in data:
            if byte != 0x0D: # Not a carriage return
                if message is None:
                    message = Message()  # Start a new message if not already started
                    message.payload = []
                message.payload.append(byte)  # Add current byte to the message payload
            else: # Carriage return recieved
                if message is not None:  # If there's a message being constructed
                    completed_messages.append(message)  # Add the completed message to the list
                    message = None  # Reset the message to start a new one
                self._last_message = None  # Reset the last message                
        # If a message is not terminated by a newline at the end of the data,
        # keep it as the last message to continue with the next incoming data.
        self._last_message = message

        for message in completed_messages:
            self.process_message(message)  # Process each completed message

    def process_message(self, message):
        self.log("Processing message: " + str(message))
        self.run_delayed_gcode(str(message))
        
    def run_delayed_gcode(self, gcode, callback=None):
        self._gcode_callbacks[
            str(time.time())] = {"gcode": gcode, "callback": callback}

        self.reactor.register_timer(
            self.gcode_command_timer, self.reactor.monotonic())

    def gcode_command_timer(self, eventtime):
        with self.mutex:
            for time in list(self._gcode_callbacks.keys()):
                command = self._gcode_callbacks[time]
                del self._gcode_callbacks[time]
                code = command["gcode"]
                callback = command["callback"]

                self.log("Running delayed gcode: " + code)
                try:
                    self.gcode.run_script(code,True)
                    if callback:
                        callback()
                except Exception as e:
                    self.error("Error running gcode script: " + str(e))
                self.log("Running delayed complete: " + code)

            return self.reactor.NEVER
        
    def gcode_output_handler(self, msg):
        self._last_gcode_output = msg
        self.send_text(msg)

    def send_text(self, text):
        self.serial_bridge.send_text(text)

    def log(self, msg, *args, **kwargs):
        if self._logging:
            logging.info("SerialHost: " + str(msg))

    def error(self, msg, *args, **kwargs):
        logging.error("SerialHost: " + str(msg))

def load_config(config):
    return SerialHost(config)
    
class Message:
    def __init__(self):
        self.payload = []

    def __str__(self):
        return bytes(self.payload).decode('utf-8')