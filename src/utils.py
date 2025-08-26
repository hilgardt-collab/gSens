import subprocess
import threading
from gi.repository import GLib, Gtk
import os 
import re 
from ui_helpers import CustomDialog

def populate_defaults_from_model(config, model):
    """
    Helper function to populate a configuration dictionary with default values
    from a given configuration model.
    """
    for section in model.values():
        for option in section:
            config.setdefault(option.key, str(option.default))

def show_confirmation_dialog(parent, title, primary_text, secondary_text=None, ok_text="_OK", ok_style="suggested-action", cancel_text="_Cancel"):
    """
    Displays a standardized, blocking confirmation dialog using CustomDialog.
    """
    icon_name = "dialog-question-symbolic"
    if ok_style == "destructive-action":
        icon_name = "dialog-warning-symbolic"
    
    dialog = CustomDialog(
        parent=parent, 
        title=title, 
        primary_text=primary_text,
        secondary_text=secondary_text,
        icon_name=icon_name,
        modal=True
    )
    
    dialog.add_styled_button(cancel_text, Gtk.ResponseType.CANCEL)
    dialog.add_styled_button(ok_text, Gtk.ResponseType.OK, style_class=ok_style, is_default=True)
    
    response = dialog.run()
    dialog.destroy()
    return response

def safe_subprocess(command, fallback="N/A", timeout=2):
    process = None
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors='replace', close_fds=True,
        )
        output, error = "", ""
        try:
            output, error = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"Timeout for command: {' '.join(command)}. Terminating...")
            process.terminate()
            try:
                # Give it a moment to terminate before killing
                output, error = process.communicate(timeout=0.5) 
            except subprocess.TimeoutExpired:
                print(f"Command did not terminate gracefully after SIGTERM. Killing...")
                process.kill()
                output, error = process.communicate(timeout=0.5) 
            except Exception as e_comm_after_term:
                print(f"Exception during communicate after SIGTERM for '{' '.join(command)}': {e_comm_after_term}")
            return fallback
        except Exception as e_comm:
            print(f"Error during communicate for '{' '.join(command)}': {e_comm}")
            if process.poll() is None:
                process.kill()
                process.wait()
            return fallback
            
        retcode = process.returncode
        if retcode == 0:
            return output.strip() if output else ""
        else:
            if error and error.strip():
                print(f"Error in subprocess command '{' '.join(command)}' (code {retcode}): {error.strip()}")
            elif output and output.strip():
                 print(f"Output (possibly error) from command '{' '.join(command)}' (code {retcode}): {output.strip()}")
            elif retcode is not None:
                # This can happen if the command exits non-zero but prints nothing
                pass
            return fallback
            
    except FileNotFoundError:
        # Don't print an error if the command is just not installed (e.g. nvidia-smi)
        # It's an expected condition on many systems.
        return fallback
    except Exception as e:
        print(f"An unexpected error occurred with command '{' '.join(command)}': {e}")
        if process and process.poll() is None:
            process.kill()
            process.wait()
        return fallback
    finally:
        # Final cleanup check
        if process and process.poll() is None:
            print(f"Process for '{' '.join(command)}' not waited for in main try, attempting cleanup.")
            if process.stdout and not process.stdout.closed:
                try: process.stdout.close()
                except OSError: pass
            if process.stderr and not process.stderr.closed:
                try: process.stderr.close()
                except OSError: pass
            try:
                process.kill()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired, Exception):
                pass

