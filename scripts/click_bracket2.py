"""Find the visible bracket-toggle and click it to expand TP/SL inputs."""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

# Find all bracket-toggle divs and their visibility
toggles = driver.execute_script("""
    return Array.from(document.querySelectorAll('.bracket-toggle')).map(function(el){
        var r = el.getBoundingClientRect();
        var cb = el.querySelector('.bracket-checkbox');
        return {
            visible: el.offsetParent !== null,
            width: r.width, height: r.height,
            top: r.top, left: r.left,
            checkboxClass: cb ? cb.className : 'N/A',
            checkboxHTML: cb ? cb.outerHTML.slice(0,200) : 'N/A'
        };
    });
""")
print(f"bracket-toggle elements ({len(toggles)}):")
for i, t in enumerate(toggles):
    print(f"  #{i}: visible={t['visible']} w={t['width']} h={t['height']} top={t['top']} cbClass={repr(t['checkboxClass'])}")

# Find visible bracket-toggle elements with a Selenium find
all_toggles = driver.find_elements(By.CSS_SELECTOR, ".bracket-toggle")
print(f"\nSelenium found {len(all_toggles)} .bracket-toggle elements")
for i, el in enumerate(all_toggles):
    displayed = el.is_displayed()
    size = el.size
    loc = el.location
    print(f"  #{i}: is_displayed={displayed} size={size} loc={loc}")

# Click the visible one's bracket-label (the whole row)
for i, el in enumerate(all_toggles):
    if el.is_displayed():
        print(f"\nClicking visible toggle #{i} bracket-label...")
        label = el.find_elements(By.CSS_SELECTOR, ".bracket-label")
        if label:
            print(f"  label is_displayed={label[0].is_displayed()}, size={label[0].size}")
            ActionChains(driver).move_to_element(label[0]).click().perform()
            time.sleep(1.0)
        break

# Check inputs after click
inputs = driver.execute_script("""
    return Array.from(document.querySelectorAll('input[placeholder="0.00"]')).map(function(el){
        var r = el.getBoundingClientRect();
        return {visible: el.offsetParent !== null, w: r.width, h: r.height,
                value: el.value, parentCls: el.parentElement ? el.parentElement.className : ''};
    });
""")
print(f"\nAfter click — input[placeholder='0.00'] ({len(inputs)}):")
for i, inp in enumerate(inputs):
    print(f"  #{i}: {inp}")

driver.service.stop()
